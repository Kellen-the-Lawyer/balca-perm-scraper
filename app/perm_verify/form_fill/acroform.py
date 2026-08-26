"""Safe helpers for filling and validating interactive PDF AcroForms."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from pypdf import PdfReader


class AcroFormValidationError(ValueError):
    """Raised when a form cannot be filled or does not reopen correctly."""


def _expected_text(value: Any, is_button: bool) -> str:
    text = str(value)
    return text.lstrip("/") if is_button else text


def _add_watermark(document: Any, text: str) -> None:
    """Add a visible training mark over the page while preserving form widgets."""

    import fitz

    for page in document:
        box = page.rect
        rect = fitz.Rect(36, box.height * 0.46, box.width - 36, box.height * 0.54)
        page.insert_textbox(
            rect,
            text,
            fontsize=24,
            fontname="helv",
            color=(0.8, 0.0, 0.0),
            align=fitz.TEXT_ALIGN_CENTER,
            fill_opacity=0.16,
            overlay=True,
        )


def _write_widget_appearances(
    template: Path,
    output: Path,
    values: Mapping[str, Any],
    widget_values: Mapping[tuple[int, str], Any],
    watermark: str | None,
) -> None:
    """Write values with native widget appearances that render without a viewer refresh."""

    import fitz

    document = fitz.open(template)
    updated: set[str] = set()
    updated_widget_keys: set[tuple[int, str]] = set()
    for page_number, page in enumerate(document, 1):
        button_widgets: dict[str, list[Any]] = {}
        button_values: dict[str, Any] = {}
        for widget in page.widgets() or []:
            name = widget.field_name
            key = (page_number, name)
            if name not in values and key not in widget_values:
                continue
            requested = widget_values.get(key, values.get(name))
            if widget.field_type_string in {"CheckBox", "RadioButton"}:
                button_widgets.setdefault(name, []).append(widget)
                button_values[name] = requested
            else:
                widget.field_value = "" if requested is None else str(requested)
                if widget.rect.height > 30:
                    widget.field_flags |= fitz.PDF_TX_FIELD_IS_MULTILINE
                    widget.text_fontsize = 7
                else:
                    widget.text_fontsize = max(
                        6, min(8, widget.rect.height * 0.45)
                    )
                widget.update()
            updated.add(name)
            updated_widget_keys.add(key)
        for name, widgets in button_widgets.items():
            requested_state = str(button_values[name]).lstrip("/")
            for widget in widgets:
                widget.field_value = False
                widget.update()
            if requested_state.lower() != "off":
                matching = [
                    widget for widget in widgets if widget.on_state() == requested_state
                ]
                if not matching:
                    document.close()
                    raise AcroFormValidationError(
                        f"{template.name} field {name!r} has no export state "
                        f"{requested_state!r}"
                    )
                matching[0].field_value = True
                matching[0].update()

    missing_widgets = sorted(set(values) - updated)
    if missing_widgets:
        document.close()
        raise AcroFormValidationError(
            f"{template.name} has mapped fields without page widgets: {missing_widgets}"
        )
    missing_widget_overrides = sorted(set(widget_values) - updated_widget_keys)
    if missing_widget_overrides:
        document.close()
        raise AcroFormValidationError(
            f"{template.name} has page-specific mappings without widgets: "
            f"{missing_widget_overrides}"
        )

    if watermark:
        _add_watermark(document, watermark)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    document.save(output, garbage=0, deflate=True)
    document.close()


def _widget_inventory(reader: PdfReader) -> dict[str, list[dict[str, Any]]]:
    inventory: dict[str, list[dict[str, Any]]] = {}
    object_names: dict[tuple[int, int], str] = {}
    for field_name, field in (reader.get_fields() or {}).items():
        reference = field.indirect_reference
        if reference is not None:
            object_names[(reference.idnum, reference.generation)] = field_name
        for child in field.get("/Kids", []) or []:
            object_names[(child.idnum, child.generation)] = field_name
    for page_number, page in enumerate(reader.pages, 1):
        for ref in page.get("/Annots", []) or []:
            widget = ref.get_object()
            if widget.get("/Subtype") != "/Widget":
                continue
            parent_ref = widget.get("/Parent")
            parent = parent_ref.get_object() if parent_ref else None
            name = object_names.get((ref.idnum, ref.generation))
            if name is None:
                name = widget.get("/T") or (parent.get("/T") if parent else None)
            if name is None:
                continue
            effective_value = widget.get("/V")
            if effective_value is None and parent is not None:
                effective_value = parent.get("/V")
            appearance = widget.get("/AP", {}).get("/N")
            inventory.setdefault(str(name), []).append(
                {
                    "page": page_number,
                    "value": str(effective_value) if effective_value is not None else None,
                    "appearance": appearance,
                    "appearance_state": (
                        str(widget.get("/AS")) if widget.get("/AS") is not None else None
                    ),
                }
            )
    return inventory


def fill_interactive_pdf(
    template: Path,
    output: Path,
    values: Mapping[str, Any],
    *,
    watermark: str | None = None,
    widget_values: Mapping[tuple[int, str], Any] | None = None,
) -> dict[str, Any]:
    """Fill a blank AcroForm, reopen it, and verify fields and appearances.

    The output remains interactive.  The input template is never modified.
    """

    page_widget_values = dict(widget_values or {})
    reader = PdfReader(template)
    source_fields = reader.get_fields() or {}
    missing = sorted(set(values) - set(source_fields))
    if missing:
        raise AcroFormValidationError(
            f"{template.name} does not contain mapped fields: {missing}"
        )
    source_widgets = _widget_inventory(reader)
    missing_page_widgets = sorted(
        key
        for key in page_widget_values
        if not any(item["page"] == key[0] for item in source_widgets.get(key[1], []))
    )
    if missing_page_widgets:
        raise AcroFormValidationError(
            f"{template.name} does not contain page-specific widgets: "
            f"{missing_page_widgets}"
        )

    _write_widget_appearances(
        template, output, values, page_widget_values, watermark
    )

    reopened = PdfReader(output)
    reopened_fields = reopened.get_fields() or {}
    widgets = _widget_inventory(reopened)
    errors: list[str] = []
    page_specific_names = {name for _, name in page_widget_values}
    for name, requested in values.items():
        field = reopened_fields.get(name)
        if field is None:
            errors.append(f"missing canonical field after reopen: {name}")
            continue
        is_button = field.get("/FT") == "/Btn"
        expected = _expected_text(requested, is_button)
        if name not in page_specific_names:
            actual = field.get("/V")
            actual_text = "" if actual is None and not is_button else str(actual)
            if is_button:
                actual_text = actual_text.lstrip("/")
            if actual_text != expected:
                errors.append(f"{name}: stored {actual!s}, expected {expected}")
        field_widgets = widgets.get(name, [])
        if not field_widgets:
            errors.append(f"{name}: no page widget after reopen")
            continue
        if not any(item["appearance"] is not None for item in field_widgets):
            errors.append(f"{name}: widget has no normal appearance stream")
        if is_button and name not in page_specific_names:
            expected_state = "/" + expected
            states = [item["appearance_state"] for item in field_widgets]
            state_matches = (
                all(state == "/Off" for state in states)
                if expected == "Off"
                else expected_state in states
            )
            if not state_matches:
                errors.append(
                    f"{name}: widget appearance state does not match {expected_state}"
                )

    for (page_number, name), requested in page_widget_values.items():
        field = reopened_fields.get(name)
        is_button = field is not None and field.get("/FT") == "/Btn"
        expected = _expected_text(requested, is_button)
        page_widgets = [
            item for item in widgets.get(name, []) if item["page"] == page_number
        ]
        if not page_widgets:
            errors.append(f"{name} on page {page_number}: no widget after reopen")
            continue
        if not any(item["appearance"] is not None for item in page_widgets):
            errors.append(
                f"{name} on page {page_number}: no normal appearance stream"
            )
        if is_button:
            states = [item["appearance_state"] for item in page_widgets]
            expected_state = "/" + expected
            state_matches = (
                all(state == "/Off" for state in states)
                if expected == "Off"
                else expected_state in states
            )
            if not state_matches:
                errors.append(
                    f"{name} on page {page_number}: widget appearance state "
                    f"does not match {expected_state}"
                )
        else:
            actual_values = [item["value"] or "" for item in page_widgets]
            if expected not in actual_values:
                errors.append(
                    f"{name} on page {page_number}: stored values "
                    f"{actual_values}, expected {expected}"
                )

    if errors:
        output.unlink(missing_ok=True)
        raise AcroFormValidationError("; ".join(errors))

    return {
        "template": str(template),
        "output": str(output),
        "page_count": len(reopened.pages),
        "field_count": len(reopened_fields),
        "updated_field_count": len(values),
        "page_specific_widget_count": len(page_widget_values),
        "interactive": True,
        "watermark": watermark,
    }
