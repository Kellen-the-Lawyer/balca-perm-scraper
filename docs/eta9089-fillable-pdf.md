# ETA-9089 fillable PDF service

## What is implemented

Casebase can fill the current DOL ETA-9089 application and Appendices A-D from
canonical JSON. The primary implementation is
`app/perm_verify/form_fill/eta9089.py`; it maps Casebase JSON paths to the exact
AcroForm field names in the fillable government PDFs.

The mapping covers:

| Form | Terminal fields/widgets mapped |
| --- | ---: |
| ETA-9089 application | 200 |
| Appendix A | 114 |
| Appendix B | 20 |
| Appendix C | 6 |
| Appendix D | 8 |

`app/perm_verify/form_fill/acroform.py` is the reusable PDF layer. It writes
native widget appearances, preserves interactive fields, handles grouped radio
buttons, wraps long narrative fields, and reopens every output to verify stored
values and appearance states.

## Stable command-line entry point

Use `scripts/fill_eta9089.py` for manual runs and future service integration:

```bash
python3 scripts/fill_eta9089.py INPUT.json \
  --templates-dir '/Users/Dad/Desktop/Qwen Training Documents/Blank Forms' \
  --output-dir output/pdf/eta9089-case \
  --watermark 'TRAINING EXAMPLE - NOT FOR FILING'
```

The input may be canonical `form_data` directly or a wrapper containing a
`form_data` key. The command writes one PDF for each supplied form section and a
`fill-manifest.json` recording templates, outputs, page counts, and validation
counts. The source templates are never modified.

For production drafts, omit `--watermark`. Training and synthetic examples
should always retain a conspicuous not-for-filing watermark.

## DOL disclosure proof of concept

`scripts/build_eta9089_dol_example.py` joins one raw PERM disclosure row to its
PWD row by PWD case number and builds canonical JSON. The DOL-backed fields keep
their real disclosed values; only the foreign-national/Appendix A facts are
generated, and those values are deliberately marked as synthetic.

This proves the mechanics but is not a training-approval step. Synthetic and
firm documents still require provenance, privacy classification, validation,
and a separate human-review status before they enter a training split.

## Future Casebase upload workflow

The intended application boundary is:

```text
uploaded PWD + audit/recruitment file
    -> document extraction with field-level confidence and source citations
    -> canonical ETA-9089 JSON
    -> deterministic validation and attorney correction screen
    -> fill_eta9089_package()
    -> interactive 9089 PDF + manifest
```

The PDF layer should not read PWDs or audit files directly. Extraction belongs
upstream so the attorney can inspect each proposed value, its source document,
and its confidence before generating the form. Required-field rules,
cross-document consistency checks, and an immutable audit record should gate
the final generation action.

## Government-shutdown contingency

The filler is deliberately submission-channel neutral. It can prepare an
interactive ETA-9089 suitable for a filing package, but Casebase must not assume
email filing is authorized. Any email workflow should remain behind a feature
flag and should only be enabled after DOL publishes operative shutdown filing
instructions. The instructions, destination address, allowed attachments,
signatures, naming convention, timing rules, and delivery evidence should be
stored with the generated filing record.

Even in a shutdown workflow, the attorney should approve the canonical JSON and
the rendered PDF before Casebase prepares or sends an email. Automatic sending
is a separate feature and is not part of this implementation.
