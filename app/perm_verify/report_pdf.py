"""PDF export for PERM verification results.

build_pdf(payload) -> bytes. Payload is the frontend's result object
(summary, filing_window, form meta, flags, overlay). Produces:
  1. Cover: case caption, filing window, summary counts, full flag list
     with citations (and supporting sources when cite was on).
  2. Annotated form pages: the rendered page images with RED/YELLOW flag
     markers and green checks drawn in (burned into the image so the PDF
     is self-contained work product).
"""
from __future__ import annotations
import base64
import io

from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (Image as RLImage, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

TONE = {"RED": (191, 75, 75), "YELLOW": (176, 125, 43), "OK": (39, 129, 95)}


def _draw_markers(img_b64, markers, page_meta):
    im = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
    draw = ImageDraw.Draw(im)
    sx = im.width / page_meta["w"]
    sy = im.height / page_meta["h"]
    for m in markers:
        x, y = m["x"] * sx, m["y"] * sy
        tone = TONE.get(m["kind"], TONE["OK"])
        if m["kind"] == "OK":
            r = 5
            draw.ellipse([x - 14 - r, y - r + 3, x - 14 + r, y + r + 3],
                         fill=tone, outline=(255, 255, 255))
        else:
            r = 9
            draw.ellipse([x - 20 - r, y - r + 4, x - 20 + r, y + r + 4],
                         fill=tone, outline=(255, 255, 255), width=2)
            label = m.get("rule_id", "")
            if label:
                draw.text((x - 20 + r + 4, y - 4), label, fill=tone)
    return im


def build_pdf(payload):
    flags = payload.get("flags", [])
    win = payload.get("filing_window", {})
    meta = (payload.get("form") or {}).get("meta", {})
    emp = (payload.get("form") or {}).get("A_employer", {})
    wage = (payload.get("form") or {}).get("E_job_wage", {})
    pwd = payload.get("pwd") or {}
    overlay = payload.get("overlay") or {}
    include_all = bool(payload.get("include_all_pages"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.7 * inch,
                            bottomMargin=0.6 * inch, leftMargin=0.75 * inch,
                            rightMargin=0.75 * inch,
                            title="PERM Verification Report")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=16, spaceAfter=4)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8.5,
                           textColor=colors.HexColor("#555555"))
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9.5, leading=13)
    cite = ParagraphStyle("cite", parent=body, fontSize=8.5, leftIndent=10,
                          textColor=colors.HexColor("#444444"))

    story = [Paragraph("ETA-9089 Verification Report", h1)]
    story.append(Paragraph(
        f"Case {meta.get('perm_case_number', 'uncaptioned')} · "
        f"{emp.get('legal_business_name', '')} · generated for attorney "
        f"review — not legal advice to third parties.", small))
    story.append(Spacer(1, 10))

    rows = [
        ["Presumed filing date", win.get("review_date_presumed_filing", "—"),
         "Offered wage", f"{wage.get('offered_wage_from', '—')} / "
                         f"{wage.get('wage_per', 'Year')}"],
        ["First day to file", win.get("first_day_to_file", "—"),
         "Prevailing wage", str(pwd.get("pw_minimum") or "—")],
        ["Last day to file", win.get("last_day_to_file", "—"),
         "PWD validity", f"{pwd.get('validity_from', '—')} – "
                         f"{pwd.get('validity_to', '—')}"],
        ["Window status",
         "IN WINDOW" if win.get("in_window") else "OUT OF WINDOW",
         "Flags", f"{sum(1 for f in flags if f['level']=='RED')} RED / "
                  f"{sum(1 for f in flags if f['level']=='YELLOW')} YELLOW"],
    ]
    t = Table(rows, colWidths=[1.35 * inch, 2.0 * inch, 1.35 * inch, 2.0 * inch])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#666666")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#666666")),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#dddddd")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [t, Spacer(1, 14)]

    story.append(Paragraph(f"Flags ({len(flags)})", ss["Heading2"]))
    if not flags:
        story.append(Paragraph(
            "No flags. Form is facially certifiable as of the review date.",
            body))
    for f in flags:
        tone = colors.Color(*[c / 255 for c in TONE.get(f["level"], TONE["OK"])])
        head = ParagraphStyle(f"fh{f['rule_id']}", parent=body,
                              textColor=tone, fontName="Helvetica-Bold")
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"[{f['level']}] {f['rule_id']} — § {f['section_item']}", head))
        story.append(Paragraph(f["message"], body))
        story.append(Paragraph(f"Cite ({f['citation_type']}): {f['citation']}",
                               cite))
        for s in (f.get("support") or []):
            story.append(Paragraph(
                f"↳ [{s['corpus']}] {s['source_label']}"
                f"{' · ' + s['cfr_citation'] if s.get('cfr_citation') else ''}"
                f" — {s['snippet'][:220]}…", cite))

    images = overlay.get("images") or []
    markers = overlay.get("markers") or []
    pages_meta = overlay.get("pages") or []
    flagged_pages = sorted({m["page"] for m in markers if m["kind"] != "OK"})
    page_ids = (list(range(len(images))) if include_all else flagged_pages)
    for pi in page_ids:
        if pi >= len(images):
            continue
        story.append(PageBreak())
        story.append(Paragraph(f"Annotated form — page {pi + 1}", ss["Heading2"]))
        im = _draw_markers(images[pi],
                           [m for m in markers if m["page"] == pi],
                           pages_meta[pi] if pi < len(pages_meta)
                           else {"w": 612, "h": 792})
        ibuf = io.BytesIO()
        im.save(ibuf, format="PNG")
        ibuf.seek(0)
        avail_w = 7.0 * inch
        story.append(RLImage(ibuf, width=avail_w,
                             height=avail_w * im.height / im.width))

    doc.build(story)
    return buf.getvalue()
