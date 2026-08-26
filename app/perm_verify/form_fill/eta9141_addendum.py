"""Generate FLAG-style ETA-9141 addendum pages for synthetic training packages."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import fitz
from pypdf import PdfReader, PdfWriter


SECTION_TITLES = {
    "F.a.2": "Job Duties",
    "F.b.1.b": "Other major(s) and/or field(s) of study required",
    "F.b.4.b": "Job Requirements Occupation",
    "F.b.5.a(iv)": "Special Skills, Other Special Skills or Requirements",
    "F.c.2.b": "Alternative other major(s) and/or field(s) of study required",
    "F.c.5.a(iv)": "Special Skills, Other Special Skills or Requirements",
    "F.d.3.a": "Travel Details",
    "G.8": "Additional Notes Regarding Wage Determination",
}

_FONT_CANDIDATES = {
    "regular": (
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ),
    "bold": (
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ),
}

_MAJOR_FALLBACKS = {
    "11-3021": "Computer Science, Information Systems, Engineering, or a related field.",
    "15-1252": "Computer Science, Software Engineering, Information Technology, or a related field.",
    "15-1211": "Computer Science, Business, Engineering, Information Systems, or a related field.",
    "17-3011": "Architecture or a related field.",
    "19-4099": "Biology, Chemistry, Laboratory Science, or a related field.",
}


def _get(data: Mapping[str, Any], path: str, default: Any = None) -> Any:
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return default
        value = value[part]
    return value


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.startswith('="') and text.endswith('"'):
        text = text[2:-1]
    replacements = {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "-",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text.strip()


def _is_reference(value: str) -> bool:
    lowered = value.lower().replace(" ", "")
    return "seef.a.2" in lowered or "seeaddendum" in lowered


def _resolved_major(data: Mapping[str, Any], value: Any) -> str:
    text = _text(value)
    if text and not _is_reference(text):
        return text
    soc = _text(_get(data, "determination.soc_code"))
    return _MAJOR_FALLBACKS.get(soc, "A field related to the job offered.")


def _resolved_occupation(data: Mapping[str, Any], value: Any) -> str:
    text = _text(value)
    if text and not _is_reference(text):
        return text
    title = _text(_get(data, "job_offer.job_title")) or "the job offered"
    return f"{title}, or a related position or occupation."


def _special_text(data: Mapping[str, Any], prefix: str) -> str:
    labels = (
        ("license", "License/certification"),
        ("foreign_language", "Foreign language"),
        ("residency", "Residency/fellowship"),
        ("other_special", "Other special skills or requirements"),
    )
    parts = []
    for key, label in labels:
        value = _text(_get(data, f"{prefix}.{key}"))
        if not value:
            continue
        if _is_reference(value):
            duties = _text(_get(data, "job_offer.job_duties"))
            value = (
                "Experience must include performing the occupation-specific duties "
                "and using the tools, systems, and methods described in Section F.a.2. "
                + duties
            )
        parts.append(f"{label}: {value}")
    return "\n\n".join(parts)


def eta9141_addendum_sections(
    data: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Build ordered addendum sections from canonical ETA-9141 form data."""

    sections: list[dict[str, str]] = []

    def add(section: str, content: Any) -> None:
        text = _text(content)
        if text:
            sections.append(
                {"section": section, "title": SECTION_TITLES[section], "content": text}
            )

    add("F.a.2", _get(data, "job_offer.job_duties"))
    degree = _text(_get(data, "requirements.education_level")).lower()
    if degree and degree != "none":
        add(
            "F.b.1.b",
            _resolved_major(data, _get(data, "requirements.majors")),
        )
    if _text(_get(data, "requirements.experience_required")).lower() == "yes":
        add(
            "F.b.4.b",
            _resolved_occupation(
                data, _get(data, "requirements.experience_occupation")
            ),
        )
    add("F.b.5.a(iv)", _special_text(data, "requirements"))

    if _text(_get(data, "alternate_requirements.accepted")).lower() == "yes":
        alt_degree = _text(
            _get(data, "alternate_requirements.education_level")
        ).lower()
        if alt_degree and alt_degree != "none":
            add(
                "F.c.2.b",
                _resolved_major(
                    data, _get(data, "alternate_requirements.majors")
                ),
            )
        add(
            "F.c.5.a(iv)",
            _special_text(data, "alternate_requirements"),
        )

    if _text(_get(data, "job_offer.travel_required")).lower() == "yes":
        add(
            "F.d.3.a",
            _get(data, "job_offer.travel_details")
            or "Travel to client or project sites within the United States may be required up to 10%.",
        )
    add("G.8", _get(data, "determination.notes"))
    return sections


def eta9141_with_addendum_references(
    data: Mapping[str, Any], sections: list[Mapping[str, str]]
) -> dict[str, Any]:
    """Return a fill payload whose continued fields point to their addendum pages."""

    result = deepcopy(data)
    section_ids = {item["section"] for item in sections}
    references = {
        "F.a.2": ("job_offer", "job_duties"),
        "F.b.1.b": ("requirements", "majors"),
        "F.b.4.b": ("requirements", "experience_occupation"),
        "F.c.2.b": ("alternate_requirements", "majors"),
        "F.d.3.a": ("job_offer", "travel_details"),
        "G.8": ("determination", "notes"),
    }
    for section, (container, key) in references.items():
        if section in section_ids:
            result[container][key] = f"See Addendum for Section {section}."
    for section, prefix in (
        ("F.b.5.a(iv)", "requirements"),
        ("F.c.5.a(iv)", "alternate_requirements"),
    ):
        if section not in section_ids:
            continue
        for key in ("license", "foreign_language", "residency", "other_special"):
            if result[prefix].get(key):
                result[prefix][key] = f"See Addendum for Section {section}."
    return result


def _wrap_line(text: str, width: float, font: str, size: float) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if fitz.get_text_length(candidate, fontname=font, fontsize=size) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _body_lines(content: str, width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in content.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        lines.extend(_wrap_line(paragraph.strip(), width, "helv", 8))
    return lines


def _seal_image(template: Path) -> fitz.Pixmap:
    document = fitz.open(template)
    page = document[0]
    clip = fitz.Rect(page.rect.width - 118, 22, page.rect.width - 36, 100)
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(2, 2),
        clip=clip,
        colorspace=fitz.csRGB,
        alpha=False,
    )
    document.close()
    return pixmap


def _font_file(kind: str) -> Path | None:
    return next((path for path in _FONT_CANDIDATES[kind] if path.exists()), None)


def generate_eta9141_addendum(
    form_data: Mapping[str, Any],
    sections: list[Mapping[str, str]],
    template: Path,
    output: Path,
    *,
    watermark: str | None = None,
) -> dict[str, Any]:
    """Write flattened FLAG-style addendum pages and return generation metadata."""

    if not sections:
        raise ValueError("at least one ETA-9141 addendum section is required")
    width, height = 612, 792
    body_width = width - 72
    max_lines = 43
    page_specs: list[dict[str, Any]] = []
    for item in sections:
        lines = _body_lines(_text(item["content"]), body_width)
        chunks = [lines[index : index + max_lines] for index in range(0, len(lines), max_lines)] or [[]]
        for index, chunk in enumerate(chunks):
            page_specs.append(
                {
                    "section": item["section"],
                    "title": item["title"],
                    "continued": index > 0,
                    "lines": chunk,
                }
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    document = fitz.open()
    seal = _seal_image(template)
    tracking = _text(_get(form_data, "meta.pwd_case_number"))
    status = _text(_get(form_data, "meta.case_status")) or "Synthetic Training Example"
    start = _text(_get(form_data, "meta.determination_date"))
    end = _text(_get(form_data, "meta.expiration_date"))
    total_label_pages = 4 + len(page_specs)
    regular_file = _font_file("regular")
    bold_file = _font_file("bold")

    for index, spec in enumerate(page_specs):
        page = document.new_page(width=width, height=height)
        regular_font = "casebase_regular" if regular_file else "helv"
        bold_font = "casebase_bold" if bold_file else "hebo"
        if regular_file:
            page.insert_font(fontname=regular_font, fontfile=str(regular_file))
        if bold_file:
            page.insert_font(fontname=bold_font, fontfile=str(bold_file))
        page.insert_text((36, 38), "OMB Approval: 1205-0508", fontname=regular_font, fontsize=6)
        page.insert_text((36, 48), "Expiration Date: 7/31/2026", fontname=regular_font, fontsize=6)
        page.insert_textbox(
            fitz.Rect(130, 28, width - 130, 44),
            "Application for Prevailing Wage Determination",
            fontname=regular_font,
            fontsize=9,
            align=fitz.TEXT_ALIGN_CENTER,
        )
        page.insert_textbox(
            fitz.Rect(130, 42, width - 130, 72),
            "ETA Form 9141\nU.S. Department of Labor",
            fontname=bold_font,
            fontsize=9,
            lineheight=1.15,
            align=fitz.TEXT_ALIGN_CENTER,
        )
        page.insert_image(fitz.Rect(width - 90, 24, width - 48, 66), pixmap=seal)
        page.draw_line(fitz.Point(36, 92), fitz.Point(width - 36, 92), width=1)
        page.insert_textbox(
            fitz.Rect(36, 98, width - 36, 112),
            "ADDENDUM",
            fontname=bold_font,
            fontsize=8,
            align=fitz.TEXT_ALIGN_CENTER,
        )
        title = f"Section {spec['section']}: {spec['title']}"
        if spec["continued"]:
            title += " (continued)"
        page.insert_textbox(
            fitz.Rect(36, 119, width - 36, 137),
            title,
            fontname=bold_font,
            fontsize=8,
            align=fitz.TEXT_ALIGN_CENTER,
        )

        page.insert_text((36, 166), f"Addendum for {title}", fontname=regular_font, fontsize=8)
        y = 188
        for line in spec["lines"]:
            if line:
                page.insert_text((36, y), line, fontname=regular_font, fontsize=8)
            y += 10

        if watermark:
            page.insert_textbox(
                fitz.Rect(36, height * 0.44, width - 36, height * 0.50),
                watermark,
                fontname=bold_font,
                fontsize=20,
                color=(0.8, 0, 0),
                fill_opacity=0.13,
                align=fitz.TEXT_ALIGN_CENTER,
                overlay=True,
            )

        page.draw_line(fitz.Point(36, height - 70), fitz.Point(width - 36, height - 70), width=0.75)
        page.insert_textbox(
            fitz.Rect(36, height - 67, width - 36, height - 55),
            "FOR DEPARTMENT OF LABOR USE ONLY",
            fontname=bold_font,
            fontsize=6,
            align=fitz.TEXT_ALIGN_CENTER,
        )
        page.insert_text(
            (width - 105, height - 60),
            f"Page {5 + index} of {total_label_pages}",
            fontname=regular_font,
            fontsize=6,
        )
        page.insert_text((36, height - 43), f"PW Tracking Number: {tracking}", fontname=regular_font, fontsize=6)
        page.insert_text((220, height - 43), f"Case Status: {status}", fontname=regular_font, fontsize=6)
        page.insert_text((390, height - 43), f"Validity Period: {start} to {end}", fontname=regular_font, fontsize=6)
    document.save(output, deflate=True)
    document.close()

    reopened = PdfReader(output)
    if len(reopened.pages) != len(page_specs):
        output.unlink(missing_ok=True)
        raise ValueError("ETA-9141 addendum page count changed after reopen")
    return {
        "output": str(output),
        "page_count": len(reopened.pages),
        "sections": [item["section"] for item in sections],
        "page_sections": [item["section"] for item in page_specs],
        "interactive": False,
        "watermark": watermark,
    }


def merge_eta9141_package(
    form_pdf: Path, addendum_pdf: Path, output: Path
) -> dict[str, Any]:
    """Append flattened addendum pages while preserving the base form field tree."""

    base = PdfReader(form_pdf)
    addendum = PdfReader(addendum_pdf)
    writer = PdfWriter()
    writer.clone_document_from_reader(base)
    for page in addendum.pages:
        writer.add_page(page)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with output.open("wb") as stream:
        writer.write(stream)

    reopened = PdfReader(output)
    expected_pages = len(base.pages) + len(addendum.pages)
    if len(reopened.pages) != expected_pages:
        output.unlink(missing_ok=True)
        raise ValueError("merged ETA-9141 package has the wrong page count")
    base_fields = set((base.get_fields() or {}).keys())
    merged_fields = set((reopened.get_fields() or {}).keys())
    if base_fields != merged_fields:
        output.unlink(missing_ok=True)
        raise ValueError("merged ETA-9141 package did not preserve form fields")
    return {
        "output": str(output),
        "page_count": len(reopened.pages),
        "field_count": len(merged_fields),
        "interactive_base_form": True,
        "flat_addendum": True,
    }
