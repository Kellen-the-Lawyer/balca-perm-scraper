import { useEffect, useMemo, useRef, useState } from "react";
import { Spinner } from "./common";
import { cfrTitleLabel } from "./cfrTitles";

const PROTOTYPE_API = import.meta.env.VITE_REG_NAV_API || "http://127.0.0.1:8002/api";

const MODES = [
  { id: "drawer", label: "Reader + Drawer" },
  { id: "three", label: "Three-Pane" },
  { id: "toolbar", label: "Toolbar" },
];

const SKIP_HEADING = new Set(["nonimmigrant classes"]);

function normalizeKey(value) {
  return (value || "").toLowerCase().replace(/\s+/g, "");
}

function parseParts(citation) {
  const section = citation.match(/^[^(]+/)?.[0] || citation;
  const tokens = [...citation.matchAll(/\(([^)]+)\)/g)].map(m => m[1]);
  return { section, tokens };
}

function citationFromParts(section, tokens) {
  return `${section}${tokens.map(t => `(${t})`).join("")}`;
}

function tokenKind(token) {
  if (/^\d+$/.test(token)) return "number";
  if (/^[IVXLCDM]+$/.test(token)) return "upper-roman";
  if (/^[ivxlcdm]+$/.test(token)) return "roman";
  if (/^[A-Z]+$/.test(token)) return "upper";
  if (/^[a-z]+$/.test(token)) return "lower";
  return "other";
}

const TOKEN_LEVELS = ["lower", "number", "roman", "upper", "number", "lower", "roman", "upper"];

function advanceOutlineStack(stack, token) {
  const kind = tokenKind(token);
  if (kind === "other" || kind === "upper-roman") return null;
  const expectedNext = TOKEN_LEVELS[stack.length];
  if (kind === expectedNext) return [...stack, token];
  for (let i = Math.min(stack.length - 1, TOKEN_LEVELS.length - 1); i >= 0; i -= 1) {
    if (TOKEN_LEVELS[i] === kind) return [...stack.slice(0, i), token];
  }
  return [...stack, token];
}

function nodeLabel(citation) {
  const { section, tokens } = parseParts(citation);
  if (!tokens.length) return `§ ${section}`;
  return `(${tokens[tokens.length - 1]})`;
}

function compactHeading(text, fallback) {
  const cleaned = (text || "")
    .replace(/\s+/g, " ")
    .replace(/^(\([^)]+\)\s*)+/, "")
    .trim();
  if (!cleaned) return fallback;
  return cleaned.length > 92 ? `${cleaned.slice(0, 92)}...` : cleaned;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function inferHeadingFromText(text, token, beforeOffset, fallback) {
  if (!token || !Number.isFinite(beforeOffset)) return fallback;
  const windowText = text.slice(0, Math.min(text.length, beforeOffset + 4000));
  const pattern = new RegExp(
    `^\\s*\\(${escapeRegExp(token)}\\)\\s+([^\\n]+(?:\\n(?!\\s*\\([^)]+\\)|\\s*\\d+\\s+CFR|\\s*$)[^\\n]+){0,2})`,
    "gm"
  );
  let match = null;
  for (const candidate of windowText.matchAll(pattern)) match = candidate;
  return match ? compactHeading(match[1], fallback) : fallback;
}

function getPreview(lines, startLine, sectionTitle, fallback) {
  if (sectionTitle) return sectionTitle;
  for (let i = startLine + 1; i < Math.min(lines.length, startLine + 8); i += 1) {
    const line = lines[i].text.trim();
    if (!line) continue;
    if (/^\d+\s+CFR\s+Part\s+/i.test(line)) continue;
    if (/^Title\s+\d+/i.test(line)) continue;
    if (SKIP_HEADING.has(line.toLowerCase())) continue;
    if (/\(enhanced display\)\s+page/i.test(line)) continue;
    return compactHeading(line, fallback);
  }
  return fallback;
}

function buildRegulationModel(doc) {
  const text = doc?.full_text || "";
  const title = doc?.cfr_title;
  const part = doc?.cfr_part;
  if (!text || !title || !part) {
    return { blocks: [], roots: [], nodeMap: new Map(), allNodes: [], metrics: { markers: 0, uniqueNodes: 0 } };
  }

  const sectionTitles = new Map(
    (Array.isArray(doc.sections) ? doc.sections : []).map(s => [String(s.section), s.title])
  );
  const lineMatches = [...text.matchAll(/^.*$/gm)];
  const lines = lineMatches.map(m => ({ text: m[0], start: m.index, end: m.index + m[0].length }));
  const markerRe = new RegExp(`^\\s*${title}\\s+CFR\\s+(${part}(?:\\.\\w+)?(?:\\([^)]+\\))*)\\s*$`, "i");
  const markers = [];

  lines.forEach((line, idx) => {
    const match = line.text.match(markerRe);
    if (!match) return;
    const citation = match[1];
    markers.push({
      citation,
      key: normalizeKey(citation),
      line: idx,
      start: line.start,
    });
  });

  if (!markers.length) {
    const citation = `${part}`;
    const block = {
      citation,
      key: normalizeKey(citation),
      blockKey: `${normalizeKey(citation)}-0`,
      line: 0,
      start: 0,
      text,
      heading: doc.part_name || doc.title || "Regulation text",
    };
    const node = {
      key: block.key,
      citation,
      label: `Part ${part}`,
      heading: block.heading,
      depth: 1,
      offset: 0,
      marker: block,
      blockKey: block.blockKey,
      synthetic: false,
      children: [],
    };
    return {
      blocks: [block],
      roots: [node],
      nodeMap: new Map([[node.key, node]]),
      allNodes: [node],
      metrics: { markers: 0, uniqueNodes: 1 },
    };
  }

  const blocks = markers.map((marker, idx) => {
    const next = markers[idx + 1]?.start ?? text.length;
    const raw = text.slice(marker.start, next).trim();
    const section = parseParts(marker.citation).section;
    return {
      ...marker,
      blockKey: `${marker.key}-${idx}`,
      text: raw,
      heading: getPreview(lines, marker.line, sectionTitles.get(section), nodeLabel(marker.citation)),
    };
  });

  const nodeMap = new Map();
  const ensureNode = (citation, marker = null, synthetic = false) => {
    const key = normalizeKey(citation);
    if (nodeMap.has(key)) {
      const existing = nodeMap.get(key);
      if (marker && !existing.marker) {
        existing.marker = marker;
        existing.blockKey = marker.blockKey;
        existing.offset = marker.start;
        existing.synthetic = false;
      }
      return existing;
    }
    const { section, tokens } = parseParts(citation);
    const depth = 1 + tokens.length;
    const sectionTitle = depth === 1 ? sectionTitles.get(section) : null;
    const node = {
      key,
      citation,
      label: nodeLabel(citation),
      heading: marker?.heading || sectionTitle || (synthetic ? "Subsection" : nodeLabel(citation)),
      depth,
      offset: marker?.start ?? Number.MAX_SAFE_INTEGER,
      marker,
      blockKey: marker?.blockKey || null,
      synthetic,
      children: [],
    };
    nodeMap.set(key, node);
    return node;
  };

  blocks.forEach(block => {
    const { section, tokens } = parseParts(block.citation);
    for (let i = 0; i <= tokens.length; i += 1) {
      const citation = citationFromParts(section, tokens.slice(0, i));
      ensureNode(citation, i === tokens.length ? block : null, i !== tokens.length);
    }
  });

  blocks.forEach(block => {
    const { section, tokens } = parseParts(block.citation);
    let stack = [...tokens];
    const blockLines = [...block.text.matchAll(/^.*$/gm)];
    blockLines.forEach(lineMatch => {
      const line = lineMatch[0].trim();
      const match = line.match(/^\(([A-Za-z]+|\d+)\)\s+(.{3,})/);
      if (!match) return;
      const [, token, rest] = match;
      const nextStack = advanceOutlineStack(stack, token);
      if (!nextStack) return;
      stack = nextStack;
      const citation = citationFromParts(section, stack);
      if (normalizeKey(citation) === block.key) return;
      const offset = block.start + lineMatch.index;
      ensureNode(citation, {
        ...block,
        citation,
        key: normalizeKey(citation),
        start: offset,
        heading: compactHeading(rest, nodeLabel(citation)),
      }, false);
    });
  });

  for (const node of nodeMap.values()) {
    if (!node.blockKey) {
      const firstChildBlock = [...nodeMap.values()]
        .filter(candidate => candidate.key.startsWith(node.key) && candidate.blockKey)
        .sort((a, b) => a.offset - b.offset)[0];
      if (firstChildBlock) {
        node.blockKey = firstChildBlock.blockKey;
        node.offset = firstChildBlock.offset;
      }
    }
  }

  const roots = [];
  for (const node of nodeMap.values()) {
    const { section, tokens } = parseParts(node.citation);
    if (!tokens.length) {
      roots.push(node);
      continue;
    }
    const parentCitation = citationFromParts(section, tokens.slice(0, -1));
    const parent = nodeMap.get(normalizeKey(parentCitation));
    if (parent) parent.children.push(node);
    else roots.push(node);
  }

  const sortTree = items => {
    items.sort((a, b) => a.offset - b.offset || a.citation.localeCompare(b.citation));
    items.forEach(item => sortTree(item.children));
  };
  sortTree(roots);

  const fillSyntheticHeadings = items => {
    items.forEach(node => {
      fillSyntheticHeadings(node.children);
      if (!node.synthetic || node.heading !== "Subsection") return;
      const { tokens } = parseParts(node.citation);
      const token = tokens[tokens.length - 1];
      const firstChild = node.children
        .filter(child => child.heading && child.heading !== "Subsection")
        .sort((a, b) => a.offset - b.offset)[0];
      node.heading = inferHeadingFromText(text, token, node.offset, firstChild?.heading || node.label);
    });
  };
  fillSyntheticHeadings(roots);

  return {
    blocks,
    roots,
    nodeMap,
    allNodes: [...nodeMap.values()].sort((a, b) => a.offset - b.offset),
    metrics: { markers: markers.length, uniqueNodes: nodeMap.size },
  };
}

function resolveJump(raw, activeNode, model) {
  const value = raw.trim();
  if (!value) return null;

  const cleaned = value
    .replace(/§/g, "")
    .replace(/\b\d+\s*cfr\b/ig, "")
    .replace(/\bcfr\b/ig, "")
    .trim();
  const activeSection = activeNode ? parseParts(activeNode.citation).section : model.allNodes[0]?.citation;

  const candidates = [cleaned];
  if (/^\(/.test(cleaned) && activeSection) candidates.push(`${activeSection}${cleaned}`);
  const spaced = cleaned.match(/^(\d+(?:\.\w+)?)(?:\s+(.+))$/);
  if (spaced) {
    const tokens = spaced[2].trim().split(/\s+/).filter(Boolean);
    candidates.push(citationFromParts(spaced[1], tokens));
  }
  if (!/^\d/.test(cleaned) && activeSection) {
    const tokens = cleaned.split(/\s+/).filter(Boolean);
    if (tokens.length) candidates.push(citationFromParts(activeSection, tokens));
  }

  for (const candidate of candidates) {
    const key = normalizeKey(candidate);
    if (model.nodeMap.has(key)) return model.nodeMap.get(key);
  }

  const loose = normalizeKey(candidates[candidates.length - 1] || cleaned);
  return model.allNodes.find(node => node.key.startsWith(loose) || node.citation.toLowerCase().includes(loose)) || null;
}

function buildBreadcrumb(node, model, doc) {
  if (!doc) return [];
  if (!node) {
    return [
      { label: `${doc.cfr_title} CFR`, kind: "title" },
      { label: `Part ${doc.cfr_part}`, kind: "part" },
    ].filter(item => item.label.trim());
  }
  const { section, tokens } = parseParts(node.citation);
  const crumbs = [
    { label: `${doc.cfr_title} CFR`, kind: "title" },
    { label: `Part ${doc.cfr_part}`, kind: "part" },
    { label: `§ ${section}`, kind: "node", citation: section },
  ];
  tokens.forEach((token, idx) => {
    crumbs.push({
      label: `(${token})`,
      kind: "node",
      citation: citationFromParts(section, tokens.slice(0, idx + 1)),
    });
  });
  return crumbs;
}

function useRegulationFind(blocks) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [matchIndex, setMatchIndex] = useState(0);
  const matchRefs = useRef([]);

  const matchesByBlock = useMemo(() => {
    if (!activeQuery.trim()) return { total: 0, map: new Map() };
    const escaped = activeQuery.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(escaped, "gi");
    let total = 0;
    const map = new Map();
    blocks.forEach(block => {
      const matches = [];
      for (const match of block.text.matchAll(re)) {
        matches.push({ start: match.index, end: match.index + match[0].length, id: total });
        total += 1;
      }
      if (matches.length) map.set(block.blockKey, matches);
    });
    return { total, map };
  }, [activeQuery, blocks]);

  useEffect(() => {
    const el = matchRefs.current[matchIndex];
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [matchIndex, matchesByBlock.total]);

  const commit = value => {
    setActiveQuery(value);
    setMatchIndex(0);
  };
  const next = () => setMatchIndex(i => matchesByBlock.total ? (i + 1) % matchesByBlock.total : 0);
  const prev = () => setMatchIndex(i => matchesByBlock.total ? (i - 1 + matchesByBlock.total) % matchesByBlock.total : 0);
  const close = () => {
    setOpen(false);
    setQuery("");
    setActiveQuery("");
    setMatchIndex(0);
  };

  return {
    open, setOpen, query, setQuery, activeQuery, commit, matchIndex,
    total: matchesByBlock.total, matchesByBlock: matchesByBlock.map,
    next, prev, close, matchRefs,
  };
}

function FindControl({ finder }) {
  return (
    <div className="reg-proto-find">
      {finder.open && (
        <>
          <div className="reg-proto-input-wrap">
            <input
              value={finder.query}
              onChange={e => { finder.setQuery(e.target.value); finder.commit(e.target.value); }}
              onKeyDown={e => {
                if (e.key === "Enter") e.shiftKey ? finder.prev() : finder.next();
                if (e.key === "Escape") finder.close();
              }}
              placeholder="Find in document..."
            />
            {finder.activeQuery && (
              <span>{finder.total ? `${finder.matchIndex + 1}/${finder.total}` : "0"}</span>
            )}
          </div>
          <button onClick={finder.prev} disabled={!finder.total} title="Previous match">↑</button>
          <button onClick={finder.next} disabled={!finder.total} title="Next match">↓</button>
          <button onClick={finder.close} title="Close find">×</button>
        </>
      )}
      <button className={finder.open ? "active" : ""} onClick={() => finder.setOpen(true)} title="Find in document">
        Find
      </button>
    </div>
  );
}

function JumpControl({ value, setValue, onJump, miss }) {
  return (
    <form className="reg-proto-jump" onSubmit={e => { e.preventDefault(); onJump(); }}>
      <input value={value} onChange={e => setValue(e.target.value)} placeholder="Jump to 214.2(h)(13)..." />
      <button type="submit">Jump</button>
      {miss && <span>No matching subsection</span>}
    </form>
  );
}

function OutlineNode({ node, activeKey, onJump, level = 0, compact = false }) {
  const [open, setOpen] = useState(level < 2);
  const active = node.key === activeKey;
  const hasChildren = node.children.length > 0;
  return (
    <div>
      <button
        className={`reg-proto-outline-node depth-${Math.min(node.depth, 6)}${active ? " active" : ""}`}
        style={{ paddingLeft: 10 + Math.min(level, 5) * 12 }}
        onClick={() => {
          onJump(node);
          if (hasChildren) setOpen(o => !o);
        }}
        title={`${node.citation} ${node.heading}`}
      >
        <span className="reg-proto-caret">{hasChildren ? (open ? "▾" : "▸") : ""}</span>
        <span className="mono reg-proto-node-token">{node.label}</span>
        {!compact && <span className="reg-proto-node-title">{node.heading}</span>}
      </button>
      {open && hasChildren && (
        <div>
          {node.children.map(child => (
            <OutlineNode key={child.key} node={child} activeKey={activeKey} onJump={onJump} level={level + 1} compact={compact} />
          ))}
        </div>
      )}
    </div>
  );
}

function OutlinePanel({ model, activeKey, onJump, compact = false, title = "Outline" }) {
  return (
    <aside className={`reg-proto-outline${compact ? " compact" : ""}`}>
      <div className="reg-proto-panel-title">
        <span>{title}</span>
        <span>{model.metrics.uniqueNodes.toLocaleString()}</span>
      </div>
      <div className="reg-proto-outline-scroll">
        {model.roots.map(node => (
          <OutlineNode key={node.key} node={node} activeKey={activeKey} onJump={onJump} compact={compact} />
        ))}
      </div>
    </aside>
  );
}

function buildRegDocLookup(docs) {
  const lookup = new Map();
  (docs || []).forEach(doc => {
    if (!doc?.cfr_title || !doc?.cfr_part) return;
    lookup.set(`${doc.cfr_title}:${String(doc.cfr_part).toLowerCase()}`, doc);
  });
  return lookup;
}

function parseRegCitation(raw, currentDoc) {
  const explicit = raw.match(/\b(\d+)\s+CFR\s*(?:§\s*)?([0-9]+[A-Za-z]?(?:\.[0-9A-Za-z]+)?(?:\([^)]+\))*)/i);
  if (explicit) {
    const section = explicit[2];
    return {
      title: Number(explicit[1]),
      citation: section,
      part: section.match(/^[^.()]+/)?.[0]?.toLowerCase(),
    };
  }
  const local = raw.match(/§\s*([0-9]+[A-Za-z]?(?:\.[0-9A-Za-z]+)?(?:\([^)]+\))*)/);
  if (local && currentDoc?.cfr_title) {
    const section = local[1];
    return {
      title: Number(currentDoc.cfr_title),
      citation: section,
      part: section.match(/^[^.()]+/)?.[0]?.toLowerCase(),
    };
  }
  return null;
}

function citationIntervals(text, doc, docLookup) {
  const intervals = [];
  const re = /\b\d+\s+CFR\s*(?:§\s*)?[0-9]+[A-Za-z]?(?:\.[0-9A-Za-z]+)?(?:\([^)]+\))*|§\s*[0-9]+[A-Za-z]?(?:\.[0-9A-Za-z]+)?(?:\([^)]+\))*/g;
  for (const match of text.matchAll(re)) {
    const parsed = parseRegCitation(match[0], doc);
    if (!parsed?.part) continue;
    const targetDoc = docLookup.get(`${parsed.title}:${parsed.part}`);
    if (!targetDoc) continue;
    intervals.push({
      start: match.index,
      end: match.index + match[0].length,
      text: match[0],
      parsed,
      targetDoc,
    });
  }
  return intervals;
}

function parentheticalMarkerIntervals(text) {
  const intervals = [];
  const re = /\(([A-Za-z]+|\d+)\)/g;
  for (const match of text.matchAll(re)) {
    intervals.push({
      start: match.index,
      end: match.index + match[0].length,
      text: match[0],
      type: "marker",
    });
  }
  return intervals;
}

function renderEnhancedText(block, finder, doc, docLookup, onCitationClick) {
  const matches = finder.matchesByBlock.get(block.blockKey) || [];
  const citations = citationIntervals(block.text, doc, docLookup);
  const markers = parentheticalMarkerIntervals(block.text);
  if (!matches.length && !citations.length && !markers.length) return block.text;

  const intervals = [
    ...matches.map(match => ({ ...match, type: "match" })),
    ...citations.map(citation => ({ ...citation, type: "citation" })),
    ...markers,
  ].sort((a, b) => a.start - b.start || (a.type === "match" ? -1 : 1));

  const parts = [];
  let cursor = 0;
  intervals.forEach(interval => {
    if (interval.start < cursor) return;
    if (interval.start > cursor) parts.push(block.text.slice(cursor, interval.start));
    if (interval.type === "citation") {
      parts.push(
        <button
          key={`${block.blockKey}-cite-${interval.start}`}
          className="reg-proto-citation-link"
          onClick={() => onCitationClick(interval)}
          title={`Open ${interval.parsed.title} CFR ${interval.parsed.citation}`}
        >
          {interval.text}
        </button>
      );
      cursor = interval.end;
      return;
    }
    if (interval.type === "marker") {
      parts.push(
        <span key={`${block.blockKey}-marker-${interval.start}`} className="reg-proto-paren-marker">
          {interval.text}
        </span>
      );
      cursor = interval.end;
      return;
    }
    const active = interval.id === finder.matchIndex;
    parts.push(
      <mark
        key={`${block.blockKey}-${interval.id}`}
        ref={el => { finder.matchRefs.current[interval.id] = el; }}
        className={active ? "active" : ""}
      >
        {block.text.slice(interval.start, interval.end)}
      </mark>
    );
    cursor = interval.end;
  });
  if (cursor < block.text.length) parts.push(block.text.slice(cursor));
  return parts;
}

function ReaderPane({ doc, model, activeKey, blockRefs, finder, onScroll, complex, docLookup, onCitationClick }) {
  return (
    <main className={`reg-proto-reader${complex ? " complex" : " simple"}`} onScroll={onScroll}>
      {model.blocks.map(block => (
        <section
          key={block.blockKey}
          ref={el => { blockRefs.current[block.blockKey] = el; }}
          className={`reg-proto-block${block.key === activeKey ? " active" : ""}`}
        >
          <div className="reg-proto-block-cite">{doc.cfr_title} CFR {block.citation}</div>
          <pre>{renderEnhancedText(block, finder, doc, docLookup, onCitationClick)}</pre>
        </section>
      ))}
    </main>
  );
}

function Breadcrumb({ crumbs, onNavigate }) {
  return (
    <div className="reg-proto-breadcrumb">
      {crumbs.map((crumb, idx) => (
        <span key={`${crumb.label}-${idx}`}>
          {idx > 0 && <b>/</b>}
          <button onClick={() => onNavigate?.(crumb)} title={`Open ${crumb.label}`}>
            {crumb.label}
          </button>
        </span>
      ))}
    </div>
  );
}

function MiniOutline({ model, activeKey, onJump }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? model.roots : model.roots.slice(0, 10);
  return (
    <aside className="reg-proto-mini-outline">
      <div className="reg-proto-panel-title">
        <span>Outline</span>
        <button onClick={() => setExpanded(v => !v)}>{expanded ? "Less" : "More"}</button>
      </div>
      <div className="reg-proto-outline-scroll">
        {visible.map(node => (
          <OutlineNode key={node.key} node={node} activeKey={activeKey} onJump={onJump} compact />
        ))}
      </div>
    </aside>
  );
}

function TitleOverviewPage({ doc, docs, onDocSelect, onBack }) {
  const titleDocs = useMemo(
    () => (docs || [])
      .filter(row => Number(row.cfr_title) === Number(doc?.cfr_title))
      .sort((a, b) => String(a.cfr_part).localeCompare(String(b.cfr_part), undefined, { numeric: true })),
    [docs, doc?.cfr_title]
  );
  return (
    <main className="reg-title-page">
      <div className="reg-title-page-header">
        <div>
          <div className="reg-title-page-kicker">CFR Title</div>
          <h2>{doc?.cfr_title ? cfrTitleLabel(doc.cfr_title) : "CFR Title"}</h2>
          <p>{titleDocs.length.toLocaleString()} parts available in Casebase.</p>
        </div>
        <button onClick={onBack}>Back to part</button>
      </div>
      <div className="reg-title-part-grid">
        {titleDocs.map(row => (
          <button key={row.id} className={String(row.id) === String(doc?.id) ? "active" : ""} onClick={() => onDocSelect?.(String(row.id))}>
            <span className="mono">{row.title}</span>
            <strong>{row.part_name || row.agency || "Federal regulation"}</strong>
            <small>{row.page_count || 0} pages · {row.section_count || 0} sections</small>
          </button>
        ))}
      </div>
    </main>
  );
}

export function AdaptiveRegulationReader({ doc, docs = [], docId, onDocSelect, header = null, apiError = "", loading = false, pdfUrl = "" }) {
  const [mode, setMode] = useState("drawer");
  const [readerPage, setReaderPage] = useState("reader");
  const [jump, setJump] = useState("");
  const [jumpMiss, setJumpMiss] = useState(false);
  const [pendingCitation, setPendingCitation] = useState("");
  const [activeKey, setActiveKey] = useState(null);
  const blockRefs = useRef({});
  const scrollRaf = useRef(null);

  const model = useMemo(() => buildRegulationModel(doc), [doc]);
  const effectiveActiveKey = activeKey && model.nodeMap.has(activeKey) ? activeKey : model.allNodes[0]?.key;
  const activeNode = effectiveActiveKey ? model.nodeMap.get(effectiveActiveKey) : model.allNodes[0];
  const complex = Boolean((doc?.full_text?.length || 0) > 100000 || (doc?.sections?.length || 0) > 25);
  const docLookup = useMemo(() => buildRegDocLookup(docs), [docs]);
  const titleDocs = useMemo(
    () => (docs || []).filter(row => Number(row.cfr_title) === Number(doc?.cfr_title)),
    [docs, doc?.cfr_title]
  );
  const finder = useRegulationFind(model.blocks);
  const crumbs = buildBreadcrumb(activeNode, model, doc);

  const jumpToNode = node => {
    setReaderPage("reader");
    if (!node?.blockKey) return;
    setActiveKey(node.key);
    blockRefs.current[node.blockKey]?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const submitJump = () => {
    const node = resolveJump(jump, activeNode, model);
    if (!node) {
      setJumpMiss(true);
      return;
    }
    setJumpMiss(false);
    jumpToNode(node);
  };

  const handleScroll = () => {
    if (scrollRaf.current) return;
    scrollRaf.current = requestAnimationFrame(() => {
      scrollRaf.current = null;
      let best = null;
      let bestDistance = Number.MAX_SAFE_INTEGER;
      model.blocks.forEach(block => {
        const el = blockRefs.current[block.blockKey];
        if (!el) return;
        const distance = Math.abs(el.getBoundingClientRect().top - 128);
        if (distance < bestDistance) {
          bestDistance = distance;
          best = block.key;
        }
      });
      if (best) setActiveKey(best);
    });
  };

  const handleCitationClick = interval => {
    if (String(interval.targetDoc.id) === String(docId || doc?.id)) {
      const node = resolveJump(interval.parsed.citation, activeNode, model);
      if (node) jumpToNode(node);
      return;
    }
    setPendingCitation(interval.parsed.citation);
    onDocSelect?.(String(interval.targetDoc.id));
  };

  const handleBreadcrumbNavigate = crumb => {
    if (crumb.kind === "title") {
      setReaderPage("title");
      return;
    }
    if (crumb.kind === "part") {
      setReaderPage("reader");
      model.blocks[0] && blockRefs.current[model.blocks[0].blockKey]?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    if (crumb.kind === "node") {
      const node = model.nodeMap.get(normalizeKey(crumb.citation));
      if (node) jumpToNode(node);
    }
  };

  useEffect(() => {
    if (!pendingCitation || loading || !doc) return;
    const node = resolveJump(pendingCitation, activeNode, model);
    if (node) {
      setTimeout(() => {
        jumpToNode(node);
        setPendingCitation("");
      }, 80);
    }
  }, [pendingCitation, loading, doc, model, activeNode]);

  if (apiError) {
    return (
      <div className="reg-proto-root">
        {header}
        <div style={{ padding: 24, color: "var(--red)", fontSize: 13 }}>{apiError}</div>
      </div>
    );
  }

  if (loading || !doc) {
    return (
      <div className="reg-proto-root">
        {header}
        <Spinner />
      </div>
    );
  }

  return (
    <div className={`reg-proto-root ${complex ? "is-complex" : "is-simple"}`}>
      {header}
      <div className="reg-proto-tools">
        <Breadcrumb crumbs={crumbs} onNavigate={handleBreadcrumbNavigate} />
        <div className="reg-proto-segmented" role="tablist" aria-label="Regulation reader mode">
          {MODES.map(item => (
            <button key={item.id} className={mode === item.id ? "active" : ""} onClick={() => setMode(item.id)}>
              {item.label}
            </button>
          ))}
        </div>
        <JumpControl value={jump} setValue={setJump} onJump={submitJump} miss={jumpMiss} />
        <FindControl finder={finder} />
        <div className="reg-proto-metrics">
          <span>{complex ? "Complex" : "Simple"}</span>
          <span>{model.metrics.uniqueNodes.toLocaleString()} nodes</span>
          <span>{(doc.full_text.length / 1000).toFixed(0)}k chars</span>
          {pdfUrl && <a href={pdfUrl} target="_blank" rel="noreferrer">PDF</a>}
        </div>
      </div>

      {readerPage === "title" && (
        <TitleOverviewPage doc={doc} docs={docs} onDocSelect={(id) => { setReaderPage("reader"); onDocSelect?.(id); }} onBack={() => setReaderPage("reader")} />
      )}

      {readerPage === "reader" && mode === "drawer" && (
        <div className="reg-proto-layout drawer">
          <OutlinePanel model={model} activeKey={effectiveActiveKey} onJump={jumpToNode} />
          <ReaderPane doc={doc} model={model} activeKey={effectiveActiveKey} blockRefs={blockRefs} finder={finder} onScroll={handleScroll} complex={complex} docLookup={docLookup} onCitationClick={handleCitationClick} />
        </div>
      )}

      {readerPage === "reader" && mode === "three" && (
        <div className="reg-proto-layout three">
          <aside className="reg-proto-doc-list">
            <div className="reg-proto-panel-title"><span>{doc?.cfr_title ? `${doc.cfr_title} CFR Parts` : "Parts"}</span><span>{titleDocs.length}</span></div>
            <div className="reg-proto-outline-scroll">
              {titleDocs.map(row => (
                <button key={row.id} className={String(row.id) === String(docId || doc?.id) ? "active" : ""} onClick={() => onDocSelect?.(String(row.id))}>
                  <span className="mono">{row.title}</span>
                  <span>{row.part_name || row.agency || "Federal regulation"}</span>
                  <small>{row.page_count || 0} pages</small>
                </button>
              ))}
            </div>
          </aside>
          <OutlinePanel model={model} activeKey={effectiveActiveKey} onJump={jumpToNode} title="Subsections" />
          <ReaderPane doc={doc} model={model} activeKey={effectiveActiveKey} blockRefs={blockRefs} finder={finder} onScroll={handleScroll} complex={complex} docLookup={docLookup} onCitationClick={handleCitationClick} />
        </div>
      )}

      {readerPage === "reader" && mode === "toolbar" && (
        <div className="reg-proto-layout toolbar">
          <div className="reg-proto-toolbar-reader">
            <ReaderPane doc={doc} model={model} activeKey={effectiveActiveKey} blockRefs={blockRefs} finder={finder} onScroll={handleScroll} complex={complex} docLookup={docLookup} onCitationClick={handleCitationClick} />
          </div>
          <MiniOutline model={model} activeKey={effectiveActiveKey} onJump={jumpToNode} />
        </div>
      )}
    </div>
  );
}

export function RegulationNavPrototype() {
  const [docs, setDocs] = useState([]);
  const [docId, setDocId] = useState("");
  const [doc, setDoc] = useState(null);
  const [apiError, setApiError] = useState("");

  useEffect(() => {
    fetch(`${PROTOTYPE_API}/regulations-docs`)
      .then(res => res.json())
      .then(rows => {
        setApiError("");
        const sorted = [...rows].sort((a, b) => (b.page_count || 0) - (a.page_count || 0));
        setDocs(sorted);
        const defaultDoc = rows.find(row => row.cfr_title === 8 && String(row.cfr_part) === "214") || sorted[0];
        if (defaultDoc) setDocId(String(defaultDoc.id));
      })
      .catch(() => setApiError(`Could not reach prototype API at ${PROTOTYPE_API}`));
  }, []);

  useEffect(() => {
    if (!docId) return;
    fetch(`${PROTOTYPE_API}/regulations-docs/${docId}`)
      .then(res => res.json())
      .then(data => {
        setApiError("");
        setDoc(data);
      })
      .catch(() => setApiError(`Could not load regulation ${docId} from ${PROTOTYPE_API}`));
  }, [docId]);

  const titleOptions = useMemo(() => {
    const titles = new Map();
    docs.forEach(row => {
      if (!row.cfr_title) return;
      const key = Number(row.cfr_title);
      if (!titles.has(key)) titles.set(key, { title: key, count: 0 });
      titles.get(key).count += 1;
    });
    return [...titles.values()].sort((a, b) => a.title - b.title);
  }, [docs]);

  const selectTitle = title => {
    const titleDocs = docs
      .filter(row => Number(row.cfr_title) === Number(title))
      .sort((a, b) => (b.page_count || 0) - (a.page_count || 0) || String(a.cfr_part).localeCompare(String(b.cfr_part), undefined, { numeric: true }));
    if (titleDocs[0]) setDocId(String(titleDocs[0].id));
  };

  const header = (
    <div className="reg-proto-header">
      <div className="reg-proto-title">
        <span>Adaptive CFR Navigation Prototype</span>
        <small>{doc ? `${doc.title}${doc.part_name ? ` · ${doc.part_name}` : ""}` : "Loading regulation..."}</small>
      </div>
      <select value={doc?.cfr_title || ""} onChange={e => selectTitle(e.target.value)} aria-label="CFR title">
        {titleOptions.map(row => (
          <option key={row.title} value={row.title}>
            {cfrTitleLabel(row.title)}
          </option>
        ))}
      </select>
    </div>
  );

  return (
    <AdaptiveRegulationReader
      doc={doc}
      docs={docs}
      docId={docId}
      onDocSelect={setDocId}
      header={header}
      apiError={apiError}
      loading={Boolean(docId && String(doc?.id) !== docId)}
    />
  );
}
