import { useState, useEffect, useRef } from "react";
import { API } from "./apiBase";
import { Spinner } from "./common";

export const GRAPH_OUTCOME_COLOR = {
  Affirmed:  "#34d399",
  Reversed:  "#f87171",
  Remanded:  "#fbbf24",
  Dismissed: "#5a5a68",
};

export function CitationGraphView({ onNavigate, initialQuery }) {
  const [q, setQ] = useState(initialQuery || "");
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState(null);
  const [hovered, setHovered] = useState(null);
  const svgRef = useRef(null);
  const simRef = useRef(null);
  const containerRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const search = async () => {
    if (!q.trim()) return;
    setLoading(true); setSelectedNode(null); setHovered(null); setGraphData(null);
    const res = await fetch(`${API}/search/citation-graph?q=${encodeURIComponent(q.trim())}&limit=40`);
    const data = await res.json();
    setGraphData(data);
    setLoading(false);
  };

  useEffect(() => { if (initialQuery?.trim()) search(); }, []);

  useEffect(() => {
    if (!graphData || !svgRef.current || !graphData.nodes.length) return;
    const d3 = window.d3;
    if (!d3) return;

    const container = svgRef.current.parentElement;
    const width = container.clientWidth || 900;
    const height = container.clientHeight || 600;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    svg.attr("width", width).attr("height", height);

    // ── Compute citation counts ──────────────────────────────────────────
    // Count how many edges point INTO each node (in-degree across all nodes)
    const inDegree = {};
    graphData.nodes.forEach(n => { inDegree[n.id] = 0; });
    graphData.edges.forEach(e => {
      if (inDegree[e.target] !== undefined) inDegree[e.target]++;
    });

    // Node radius: size purely by in-degree (citations received), min 10
    const maxDegree = Math.max(...Object.values(inDegree), 1);
    const nodeRadius = (n) => {
      const deg = inDegree[n.id] || 0;
      // secondary nodes get bonus from their cited_by_count too
      const effectiveDeg = n.tier === "secondary"
        ? Math.max(deg, n.cited_by_count || 0)
        : deg;
      return 10 + (effectiveDeg / maxDegree) * 28;
    };

    // ── Zoom & pan ───────────────────────────────────────────────────────
    const zoom = d3.zoom().scaleExtent([0.25, 4]).on("zoom", e => {
      g.attr("transform", e.transform);
    });
    svg.call(zoom);

    const g = svg.append("g");

    // ── Arrow markers ─────────────────────────────────────────────────────
    const defs = svg.append("defs");
    // One marker per outcome color
    const markerColors = { default: "#4a4a6a", Affirmed: "#34d399", Reversed: "#f87171", Remanded: "#fbbf24", Dismissed: "#5a5a68" };
    Object.entries(markerColors).forEach(([key, color]) => {
      defs.append("marker")
        .attr("id", `arrow-${key}`)
        .attr("viewBox", "0 -4 8 8")
        .attr("refX", 10).attr("refY", 0)
        .attr("markerWidth", 7).attr("markerHeight", 7)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-4L8,0L0,4")
        .attr("fill", color)
        .attr("opacity", 0.7);
    });

    // ── Simulation ────────────────────────────────────────────────────────
    const nodes = graphData.nodes.map(n => ({ ...n }));
    const nodeById = Object.fromEntries(nodes.map(n => [n.id, n]));
    const edges = graphData.edges
      .filter(e => nodeById[e.source] && nodeById[e.target])
      .map(e => ({ ...e }));

    const sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(edges)
        .id(n => n.id)
        .distance(d => {
          const sr = nodeRadius(nodeById[d.source.id ?? d.source]);
          const tr = nodeRadius(nodeById[d.target.id ?? d.target]);
          return sr + tr + 60; // edges scale with node size so big nodes don't overlap
        })
        .strength(0.5))
      .force("charge", d3.forceManyBody().strength(n => -(nodeRadius(n) * 18)))
      .force("center", d3.forceCenter(width / 2, height / 2).strength(0.08))
      .force("collision", d3.forceCollide().radius(n => nodeRadius(n) + 20).strength(0.9))
      .alphaDecay(0.02);

    simRef.current = sim;

    // ── Edges ─────────────────────────────────────────────────────────────
    const link = g.append("g").attr("class", "links")
      .selectAll("line")
      .data(edges).join("line")
      .attr("stroke", d => {
        const src = nodeById[d.source.id ?? d.source];
        return GRAPH_OUTCOME_COLOR[src?.outcome] ?? "#4a4a6a";
      })
      .attr("stroke-width", 1.5)
      .attr("stroke-opacity", 0.45)
      .attr("marker-end", d => {
        const src = nodeById[d.source.id ?? d.source];
        const key = GRAPH_OUTCOME_COLOR[src?.outcome] ? src.outcome : "default";
        return `url(#arrow-${key})`;
      });

    // ── Node groups ───────────────────────────────────────────────────────
    const node = g.append("g").attr("class", "nodes")
      .selectAll("g")
      .data(nodes).join("g")
      .style("cursor", "pointer")
      .call(d3.drag()
        .on("start", (event, d) => {
          if (!event.active) sim.alphaTarget(0.15).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end", (event, d) => {
          if (!event.active) sim.alphaTarget(0);
          d.fx = null; d.fy = null;
        })
      );

    // Circle
    node.append("circle")
      .attr("r", nodeRadius)
      .attr("fill", n => {
        const base = GRAPH_OUTCOME_COLOR[n.outcome] ?? "#5a5a68";
        return n.tier === "secondary" ? base + "55" : base + "cc";
      })
      .attr("stroke", n => GRAPH_OUTCOME_COLOR[n.outcome] ?? "#5a5a68")
      .attr("stroke-width", n => n.tier === "primary" ? 2 : 1)
      .attr("stroke-opacity", 0.9);

    // Citation count badge (centre of circle)
    node.append("text")
      .text(n => inDegree[n.id] || "")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "central")
      .attr("font-size", n => Math.max(8, nodeRadius(n) * 0.55))
      .attr("font-family", "'DM Mono', monospace")
      .attr("font-weight", "600")
      .attr("fill", "#fff")
      .attr("fill-opacity", 0.9)
      .style("pointer-events", "none");

    // Case number label below circle
    node.append("text")
      .text(n => {
        // Strip leading year+PER+zeros: "2019-PER-00042" → "2019-42"
        const m = n.case_number?.match(/^(\d{4})-PER-0*(\d+)$/);
        return m ? `${m[1]}-${m[2]}` : (n.case_number ?? "");
      })
      .attr("text-anchor", "middle")
      .attr("dy", n => nodeRadius(n) + 13)
      .attr("font-size", 9)
      .attr("font-family", "'DM Mono', monospace")
      .attr("fill", n => GRAPH_OUTCOME_COLOR[n.outcome] ?? "#8888aa")
      .attr("fill-opacity", n => n.tier === "primary" ? 0.85 : 0.55)
      .style("pointer-events", "none");

    // Employer name label (two lines max, only if node is big enough)
    node.each(function(n) {
      if (!n.employer_name) return;
      const r = nodeRadius(n);
      if (r < 18) return; // skip tiny nodes
      const label = n.employer_name.length > 22
        ? n.employer_name.slice(0, 20) + "…"
        : n.employer_name;
      d3.select(this).append("text")
        .text(label)
        .attr("text-anchor", "middle")
        .attr("dy", r + 24)
        .attr("font-size", 8.5)
        .attr("font-family", "sans-serif")
        .attr("fill", "var(--text3, #888)")
        .attr("fill-opacity", 0.7)
        .style("pointer-events", "none");
    });

    // ── Interactions ──────────────────────────────────────────────────────
    node.on("mouseenter", (event, d) => {
      setHovered(d);
      // Highlight connected edges
      link.attr("stroke-opacity", e => {
        const sid = e.source.id ?? e.source;
        const tid = e.target.id ?? e.target;
        return (sid === d.id || tid === d.id) ? 0.9 : 0.1;
      }).attr("stroke-width", e => {
        const sid = e.source.id ?? e.source;
        const tid = e.target.id ?? e.target;
        return (sid === d.id || tid === d.id) ? 2.5 : 1.5;
      });
      // Dim unconnected nodes
      const connected = new Set([d.id]);
      edges.forEach(e => {
        const sid = e.source.id ?? e.source;
        const tid = e.target.id ?? e.target;
        if (sid === d.id) connected.add(tid);
        if (tid === d.id) connected.add(sid);
      });
      node.attr("opacity", n => connected.has(n.id) ? 1 : 0.2);
    })
    .on("mouseleave", () => {
      setHovered(null);
      link.attr("stroke-opacity", 0.45).attr("stroke-width", 1.5);
      node.attr("opacity", 1);
    })
    .on("click", (event, d) => {
      event.stopPropagation();
      setSelectedNode(d);
    });

    svg.on("click", () => setSelectedNode(null));

    // ── Tick ─────────────────────────────────────────────────────────────
    sim.on("tick", () => {
      link
        .attr("x1", d => d.source.x)
        .attr("y1", d => d.source.y)
        .attr("x2", d => {
          const tr = nodeRadius(nodeById[d.target.id ?? d.target] ?? d.target);
          const dx = d.target.x - d.source.x, dy = d.target.y - d.source.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          return d.target.x - (dx / dist) * (tr + 10);
        })
        .attr("y2", d => {
          const tr = nodeRadius(nodeById[d.target.id ?? d.target] ?? d.target);
          const dx = d.target.x - d.source.x, dy = d.target.y - d.source.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          return d.target.y - (dy / dist) * (tr + 10);
        });
      node.attr("transform", d => `translate(${d.x},${d.y})`);
    });

    return () => { sim.stop(); };
  }, [graphData]);

  // Load D3 from CDN once
  useEffect(() => {
    if (window.d3) return;
    const script = document.createElement("script");
    script.src = "https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js";
    document.head.appendChild(script);
  }, []);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>

      {/* ── Search bar ── */}
      <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg2)", flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: graphData ? 8 : 0 }}>
          <div style={{ position: "relative", flex: 1, maxWidth: 600 }}>
            <svg style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text3)", pointerEvents: "none" }}
              width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
            </svg>
            <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)}
              onKeyDown={e => e.key === "Enter" && search()}
              placeholder="Search and map citations — e.g. 'business necessity' or 'Notice of Filing'"
              style={{ paddingLeft: 30, fontSize: 13, height: 36 }} />
          </div>
          <button onClick={search} className="primary" style={{ height: 36, padding: "0 18px", fontSize: 13 }}>Map</button>
          {graphData && (
            <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>
              {graphData.primary_count} matched · {graphData.secondary_count} hub · {graphData.edges.length} links
            </span>
          )}
        </div>

        {/* Legend */}
        {graphData && (
          <div style={{ display: "flex", gap: 20, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ display: "flex", gap: 10 }}>
              {Object.entries(GRAPH_OUTCOME_COLOR).map(([outcome, color]) => (
                <span key={outcome} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
                  {outcome}
                </span>
              ))}
            </div>
            <span style={{ fontSize: 10, color: "var(--text3)" }}>circle size = citations received · number inside = citation count</span>
            <span style={{ fontSize: 10, color: "var(--text3)" }}>solid = matched search · faded = cited hub · hover or tap to highlight connections</span>
          </div>
        )}
      </div>

      {/* ── Graph canvas ── */}
      <div ref={containerRef} style={{ flex: 1, position: "relative", overflow: "hidden", background: "var(--bg)" }}>

        {/* Empty state */}
        {!graphData && !loading && (
          <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14 }}>
            <svg width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="var(--border2)" strokeWidth="0.8">
              <circle cx="5" cy="12" r="2.5"/><circle cx="19" cy="5" r="2.5"/><circle cx="19" cy="19" r="2.5"/>
              <circle cx="12" cy="8" r="2"/><circle cx="12" cy="17" r="2"/>
              <line x1="7" y1="11.5" x2="10.2" y2="8.8"/><line x1="7" y1="12.5" x2="10.2" y2="16"/>
              <line x1="14" y1="8" x2="17" y2="6.2"/><line x1="14" y1="17" x2="17" y2="18.2"/>
            </svg>
            <div style={{ fontSize: 13, color: "var(--text3)", textAlign: "center" }}>
              Enter a search term to see how results cite each other
              <div style={{ fontSize: 11, marginTop: 4, color: "var(--border2)" }}>Try: "business necessity" · "alien labor certification" · "Notice of Filing"</div>
            </div>
          </div>
        )}

        {loading && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Spinner />
          </div>
        )}

        {graphData && !loading && graphData.nodes.length === 0 && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ fontSize: 13, color: "var(--text3)" }}>No results found.</div>
          </div>
        )}

        <svg ref={svgRef} className="citation-graph-svg" style={{ width: "100%", height: "100%", display: "block" }} />

        {/* Hover tooltip */}
        {hovered && !selectedNode && (
          <div style={{
            position: "absolute", bottom: 20, left: 20, zIndex: 10,
            background: "var(--bg2)", border: "1px solid var(--border2)",
            borderRadius: "var(--radius-lg)", padding: "10px 14px",
            maxWidth: 300, pointerEvents: "none",
            boxShadow: "0 4px 20px #00000055",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: GRAPH_OUTCOME_COLOR[hovered.outcome] ?? "var(--text3)", fontWeight: 600 }}>
                {hovered.case_number}
              </span>
              <span style={{ fontSize: 9, padding: "1px 6px", borderRadius: 3,
                background: hovered.tier === "primary" ? "var(--amber-dim)" : "var(--bg4)",
                color: hovered.tier === "primary" ? "var(--amber)" : "var(--text3)" }}>
                {hovered.tier === "primary" ? "matched" : `hub · cited ${hovered.cited_by_count}×`}
              </span>
            </div>
            {hovered.employer_name && (
              <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text)", marginBottom: 4, fontFamily: "'DM Serif Display', serif" }}>
                {hovered.employer_name}
              </div>
            )}
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              {hovered.date && <span style={{ fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{hovered.date}</span>}
              {hovered.outcome && (
                <span style={{ fontSize: 10, color: GRAPH_OUTCOME_COLOR[hovered.outcome], fontWeight: 500 }}>● {hovered.outcome}</span>
              )}
            </div>
            <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 6, borderTop: "1px solid var(--border)", paddingTop: 6 }}>
              Tap to open details · drag to reposition
            </div>
          </div>
        )}

        {/* Selected node panel */}
        {selectedNode && (
          <div style={{
            position: "absolute", top: 16, right: 16, zIndex: 10,
            background: "var(--bg2)", border: `1px solid ${GRAPH_OUTCOME_COLOR[selectedNode.outcome] ?? "var(--border2)"}44`,
            borderRadius: "var(--radius-lg)", padding: "16px 18px", width: 270,
            boxShadow: "0 8px 28px #00000066", animation: "fadeUp 0.15s ease",
          }}>
            <div style={{ display: "flex", alignItems: "flex-start", marginBottom: 12 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: GRAPH_OUTCOME_COLOR[selectedNode.outcome] ?? "var(--text3)", fontWeight: 600 }}>
                    {selectedNode.case_number}
                  </span>
                  <span style={{ fontSize: 9, padding: "1px 6px", borderRadius: 3,
                    background: selectedNode.tier === "primary" ? "var(--amber-dim)" : "var(--bg4)",
                    color: selectedNode.tier === "primary" ? "var(--amber)" : "var(--text3)" }}>
                    {selectedNode.tier === "primary" ? "matched" : `hub · cited ${selectedNode.cited_by_count}×`}
                  </span>
                </div>
                {selectedNode.employer_name && (
                  <div style={{ fontSize: 14, fontWeight: 400, color: "var(--text)", marginBottom: 4, fontFamily: "'DM Serif Display', serif", lineHeight: 1.3 }}>
                    {selectedNode.employer_name}
                  </div>
                )}
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                  {selectedNode.date && <span style={{ fontSize: 10, color: "var(--text3)", fontFamily: "'DM Mono', monospace" }}>{selectedNode.date}</span>}
                  {selectedNode.outcome && (
                    <span style={{ fontSize: 10, color: GRAPH_OUTCOME_COLOR[selectedNode.outcome], fontWeight: 500 }}>● {selectedNode.outcome}</span>
                  )}
                </div>
              </div>
              <button onClick={() => setSelectedNode(null)}
                style={{ fontSize: 16, lineHeight: 1, color: "var(--text3)", background: "none", border: "none", cursor: "pointer", padding: "0 2px", marginLeft: 8, flexShrink: 0 }}>×</button>
            </div>
            <button
              onClick={() => { onNavigate(selectedNode.id); setSelectedNode(null); }}
              className="primary"
              style={{ width: "100%", fontSize: 12, padding: "8px 0" }}>
              Open decision →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}


// ── AAO Citation Graph View ───────────────────────────────────────────────────

export function AAOCitationGraphView({ onNavigate, onOpenPrecedent, initialQuery }) {
  const [q, setQ] = useState(initialQuery || "");
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState(null);
  const [hovered, setHovered] = useState(null);
  const [d3Ready, setD3Ready] = useState(!!window.d3);
  const svgRef = useRef(null);
  const simRef = useRef(null);
  const containerRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  // Load D3 from CDN if not already present, then signal ready
  useEffect(() => {
    if (window.d3) { setD3Ready(true); return; }
    const script = document.createElement("script");
    script.src = "https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js";
    script.onload = () => setD3Ready(true);
    document.head.appendChild(script);
  }, []);

  const search = async () => {
    if (!q.trim()) { return; }
    setLoading(true); setSelectedNode(null); setHovered(null); setGraphData(null);
    const url = `${API}/aao/search/citation-graph?q=${encodeURIComponent(q.trim())}&limit=40`;
    try {
      const res = await fetch(url);
      const data = await res.json();
     
      setGraphData(data);
    } catch(e) {
      console.error('AAO citation graph fetch error:', e);
    }
    setLoading(false);
  };

  useEffect(() => { if (initialQuery?.trim()) search(); }, []);

  useEffect(() => {
    if (!d3Ready || !graphData || !svgRef.current || !graphData.nodes.length) return;
    const d3 = window.d3;
    if (!d3) return;

    const container = svgRef.current.parentElement;
    const width = container.clientWidth || 900;
    const height = container.clientHeight || 600;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    svg.attr("width", width).attr("height", height);

    const inDegree = {};
    graphData.nodes.forEach(n => { inDegree[n.id] = 0; });
    graphData.edges.forEach(e => { if (inDegree[e.target] !== undefined) inDegree[e.target]++; });

    const maxDegree = Math.max(...Object.values(inDegree), 1);
    const nodeRadius = (n) => {
      const deg = inDegree[n.id] || 0;
      const effectiveDeg = n.tier === "secondary" ? Math.max(deg, n.cited_by_count || 0) : deg;
      return 10 + (effectiveDeg / maxDegree) * 28;
    };

    const zoom = d3.zoom().scaleExtent([0.25, 4]).on("zoom", e => { g.attr("transform", e.transform); });
    svg.call(zoom);
    const g = svg.append("g");

    const defs = svg.append("defs");
    const markerColors = { default: "#4a4a6a", Dismissed: "#5a5a68", Sustained: "#34d399", Remanded: "#fbbf24", Withdrawn: "#a78bfa" };
    Object.entries(markerColors).forEach(([key, color]) => {
      defs.append("marker")
        .attr("id", `aao-arrow-${key}`)
        .attr("viewBox", "0 -4 8 8").attr("refX", 10).attr("refY", 0)
        .attr("markerWidth", 7).attr("markerHeight", 7).attr("orient", "auto")
        .append("path").attr("d", "M0,-4L8,0L0,4").attr("fill", color).attr("opacity", 0.7);
    });

    const nodes = graphData.nodes.map(n => ({ ...n }));
    const nodeById = Object.fromEntries(nodes.map(n => [n.id, n]));
    const edges = graphData.edges.filter(e => nodeById[e.source] && nodeById[e.target]).map(e => ({ ...e }));

    const sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(edges).id(n => n.id)
        .distance(d => {
          const sr = nodeRadius(nodeById[d.source.id ?? d.source]);
          const tr = nodeRadius(nodeById[d.target.id ?? d.target]);
          return sr + tr + 60;
        }).strength(0.5))
      .force("charge", d3.forceManyBody().strength(n => -(nodeRadius(n) * 18)))
      .force("center", d3.forceCenter(width / 2, height / 2).strength(0.08))
      .force("collision", d3.forceCollide().radius(n => nodeRadius(n) + 20).strength(0.9))
      .alphaDecay(0.02);
    simRef.current = sim;

    const outcomeColor = (o) => ({ Dismissed: "#5a5a68", Sustained: "#34d399", Remanded: "#fbbf24", Withdrawn: "#a78bfa" }[o] || "#60a5fa");
    const nodeColor = (n) => n.node_type === "precedent" ? "#2dd4bf" : outcomeColor(n.outcome);
    const nodeFill  = (n) => n.node_type === "precedent"
      ? (n.tier === "primary" ? "#2dd4bf" : "#2dd4bf88")
      : (n.tier === "primary" ? outcomeColor(n.outcome) : outcomeColor(n.outcome) + "66");

    const link = g.append("g").selectAll("line").data(edges).join("line")
      .attr("stroke", d => {
        const tgt = nodeById[d.target?.id ?? d.target];
        return tgt?.node_type === "precedent" ? "#2dd4bf" : outcomeColor(tgt?.outcome);
      })
      .attr("stroke-opacity", 0.35).attr("stroke-width", 1.5)
      .attr("marker-end", d => {
        const tgt = nodeById[d.target?.id ?? d.target];
        if (tgt?.node_type === "precedent") return "url(#aao-arrow-default)";
        const key = markerColors[tgt?.outcome] ? tgt?.outcome : "default";
        return `url(#aao-arrow-${key})`;
      });

    const node = g.append("g").selectAll("g").data(nodes).join("g")
      .style("cursor", "pointer")
      .call(d3.drag()
        .on("start", (event, d) => { if (!event.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag",  (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end",   (event, d) => { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }))
      .on("click", (event, d) => {
        event.stopPropagation();
        if (d.node_type === "precedent" && onOpenPrecedent) {
          onOpenPrecedent(d.prec_id);
        } else {
          setSelectedNode(d);
        }
      })
      .on("mouseover", (event, d) => setHovered(d))
      .on("mouseout",  () => setHovered(null));

    node.append("circle")
      .attr("r", nodeRadius)
      .attr("fill", nodeFill)
      .attr("stroke", d => d.tier === "primary" ? (d.node_type === "precedent" ? "#fde68a" : "#fff") : "none")
      .attr("stroke-width", d => d.tier === "primary" ? 2 : 0)
      .attr("opacity", d => d.tier === "primary" ? 1 : 0.65);

    node.append("text")
      .attr("dy", "0.35em").attr("text-anchor", "middle")
      .attr("font-size", d => Math.max(9, Math.min(13, nodeRadius(d) * 0.55)))
      .attr("fill", "#fff").attr("pointer-events", "none")
      .text(d => {
        const label = d.node_type === "precedent"
          ? (d.party_name || d.citation || "")
          : (d.form_type || d.label || d.filename || "");
        return label.length > 14 ? label.slice(0, 13) + "…" : label;
      });

    sim.on("tick", () => {
      link
        .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
      node.attr("transform", d => `translate(${d.x},${d.y})`);
    });

    svg.on("click", () => setSelectedNode(null));
    return () => sim.stop();
  }, [graphData, d3Ready]);

  const accent = "#60a5fa";

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--bg)" }} ref={containerRef}>
      {/* Header */}
      <div style={{ padding: "20px 24px 16px", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={accent} strokeWidth="1.8">
            <circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/>
            <line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/>
          </svg>
          <span style={{ fontFamily: "'DM Serif Display', serif", fontSize: 18, color: "var(--text)" }}>AAO Citation Graph</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <div style={{ flex: 1, position: "relative" }}>
            <svg style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", opacity: 0.4 }} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
            <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === "Enter" && search()}
              placeholder="Search AAO decisions or enter form type (I-140, I-485…)"
              style={{ width: "100%", paddingLeft: 30, fontSize: 13, height: 36, boxSizing: "border-box" }} />
          </div>
          <button onClick={search} disabled={loading} style={{ background: accent, color: "#fff", border: "none", borderRadius: 6, padding: "0 16px", fontSize: 13, cursor: "pointer", opacity: loading ? 0.6 : 1 }}>
            {loading ? "…" : "Graph"}
          </button>
        </div>
        {graphData && (
          <div style={{ marginTop: 10, fontSize: 11, color: "var(--text3)" }}>
            {graphData.primary_count} primary · {graphData.secondary_count} secondary · {graphData.edges.length} edges
          </div>
        )}
      </div>

      {/* Graph canvas */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
        {!graphData && !loading && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12, opacity: 0.5 }}>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke={accent} strokeWidth="1"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><line x1="7" y1="12" x2="17" y2="6"/><line x1="7" y1="12" x2="17" y2="18"/></svg>
            <span style={{ fontSize: 13, color: "var(--text3)" }}>Search to generate citation graph</span>
          </div>
        )}
        {loading && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <span style={{ fontSize: 13, color: "var(--text3)" }}>Building graph…</span>
          </div>
        )}
        <svg ref={svgRef} style={{ width: "100%", height: "100%", display: "block" }} />

        {/* Hover tooltip */}
        {hovered && (
          <div style={{ position: "absolute", bottom: 16, left: 16, background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: 8, padding: "10px 14px", maxWidth: 300, pointerEvents: "none" }}>
            {hovered.node_type === "precedent" ? (
              <>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#2dd4bf", marginBottom: 3 }}>{hovered.party_name}</div>
                <div style={{ fontSize: 11, color: "var(--text2)", marginBottom: 3 }}>{hovered.citation} · {hovered.year}</div>
                <div style={{ fontSize: 11, color: "var(--text3)" }}>Cited by {hovered.cited_by_count} decisions in graph · I&N Dec. precedent</div>
              </>
            ) : (
              <>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", marginBottom: 3 }}>{hovered.form_type || hovered.label || hovered.filename}</div>
                {hovered.label && hovered.label !== hovered.form_type && <div style={{ fontSize: 11, color: "var(--text2)", marginBottom: 3 }}>{hovered.label.slice(0, 80)}</div>}
                <div style={{ fontSize: 11, color: "var(--text3)" }}>{hovered.date} · {hovered.outcome || "—"} · <span style={{ color: accent }}>{hovered.tier}</span></div>
              </>
            )}
          </div>
        )}

        {/* Selected node panel */}
        {selectedNode && (
          <div style={{ position: "absolute", top: 16, right: 16, width: 280, background: "var(--bg2)", border: `1px solid ${accent}44`, borderRadius: 10, padding: "14px 16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: selectedNode.node_type === "precedent" ? "#2dd4bf" : "var(--text)", flex: 1, paddingRight: 8 }}>
                {selectedNode.node_type === "precedent" ? selectedNode.party_name : (selectedNode.form_type || selectedNode.filename)}
              </div>
              <button onClick={() => setSelectedNode(null)} style={{ background: "none", border: "none", color: "var(--text3)", cursor: "pointer", fontSize: 16, padding: 0, lineHeight: 1 }}>×</button>
            </div>
            {selectedNode.node_type === "precedent" ? (
              <>
                <div style={{ fontSize: 11, color: "var(--text2)", marginBottom: 4 }}>{selectedNode.citation} · {selectedNode.year}</div>
                <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 12 }}>Cited by {selectedNode.cited_by_count} decisions in this graph</div>
                {onOpenPrecedent && <button onClick={() => onOpenPrecedent(selectedNode.prec_id)}
                  style={{ width: "100%", padding: "7px 0", background: "#2dd4bf22", color: "#2dd4bf", border: "1px solid #2dd4bf44", borderRadius: 6, fontSize: 12, cursor: "pointer", fontWeight: 500 }}>
                  Open precedent →
                </button>}
              </>
            ) : (
              <>
                {selectedNode.label && selectedNode.label !== selectedNode.form_type && (
                  <div style={{ fontSize: 11, color: "var(--text2)", marginBottom: 8 }}>{selectedNode.label.slice(0, 120)}</div>
                )}
                <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 12 }}>{selectedNode.date} · {selectedNode.outcome || "—"} · {selectedNode.tier}</div>
                <button onClick={() => onNavigate(selectedNode.id)}
                  style={{ width: "100%", padding: "7px 0", background: accent + "22", color: accent, border: `1px solid ${accent}44`, borderRadius: 6, fontSize: 12, cursor: "pointer", fontWeight: 500 }}>
                  Open decision →
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Landing page ──────────────────────────────────────────────────────────────
