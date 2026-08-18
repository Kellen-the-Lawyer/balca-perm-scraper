# Synthetic PWD/PERM training data

## Purpose

Casebase uses one versioned record to describe a linked ETA-9141 PWD and
ETA-9089 PERM case.  The same record is intended to support:

1. semi-synthetic case generation from joined OFLC disclosure records;
2. rendering draft forms in FLAG or another renderer;
3. supervised document-extraction examples;
4. deterministic PWD/PERM comparison tests; and
5. future Antigravity/Graphite field mappings.

The canonical model is in
`app/perm_verify/synthetic/models.py`.  Its generated JSON Schema is checked in
at `app/perm_verify/synthetic/schemas/perm_pwd_pair.v1.schema.json`, and a
fictional example is at
`app/perm_verify/synthetic/examples/oflc_pair_seed.example.json`.

## Record lifecycle

Each pair moves through four explicit stages:

| Stage | Meaning |
| --- | --- |
| `seed` | Available OFLC or reviewed-firm facts have been mapped; missing form fields are allowed. |
| `generated` | Synthetic rules have completed the intended form fields and passed dependency checks. |
| `rendered` | FLAG or another renderer has produced document artifacts; hashes and page counts are recorded. |
| `reviewed` | A human has certified the selected record or corrected its sidecar JSON. |

The form values live in `pwd.form_data` and `perm.form_data`.  Provenance and
visual grounding live separately in each document's `annotations` dictionary,
keyed by canonical paths such as:

- `meta.pwd_case_number`
- `primary_requirements.experience_months`
- `E_job_wage.pwd_case_number`
- `H_recruitment.swa_job_order_start`

This keeps clean JSON values available to FLAG while preserving the richer
metadata required for extraction training.

## OFLC seed mapping

`build_pair_seed()` in `app/perm_verify/synthetic/oflc_seed.py` accepts one
`oflc_perm` row and its matching `oflc_pw` row.  It rejects the pair unless the
PERM `pwd_number` exactly matches the PW `case_number`.

The function maps disclosure fields that correspond to printed form fields and
records the source table and column for each value.  Disclosure facts such as
job title and SOC classification that describe the case but are not necessarily
printed in the current ETA-9089 sections are retained under
`shared_case_facts`; they are not silently inserted into an unrelated form
section.

An OFLC seed is not a completed form.  The disclosure data does not contain all
PWD requirements, contact details, recruitment dates, Appendix A history, or
conditional explanations.  Rules must create those fields before a seed is
promoted to `generated`.

## Provenance rules

Every populated training field should eventually have an annotation identifying
one of these origins:

- `oflc_perm` or `oflc_pw`: direct or documented transformation from disclosure data;
- `shared_case_fact`: copied consistently into both documents;
- `synthetic_rule`: created by a named, versioned generation rule;
- `firm_document`: transcribed from a real firm document;
- `deterministic_parser`: proposed by an existing extractor;
- `human_review`: corrected or certified by a reviewer.

Generated records must not be marked `training_approved` merely because they
validate structurally.  Training approval is a separate privacy and quality
decision.

## Real firm pairs

Firm-created PWD/PERM pairs should enter the same contract with
`source_type: firm_real` and `privacy.classification: confidential_firm`.
Deterministic extraction can populate the first sidecar.  A reviewer should
correct disagreements and representative agreements; corrections receive
`human_review` provenance.  Raw confidential documents should not be committed
to the repository.

## FLAG mapping boundary

The current Antigravity `FLAGPWDService` and `FLAGPERMService` contain useful
model-to-form intent, but their selectors are explicitly placeholders.  The
canonical JSON paths created here should be the left side of the eventual FLAG
mapping table:

```text
canonical JSON path -> FLAG page/step -> control selector -> transformation
```

Selector discovery belongs in a separate, versioned mapping artifact because a
FLAG UI change must not require changing the training-data contract.  The same
mapping artifact can be consumed by both Antigravity and Graphite.

## Planned build sequence

1. Certify the complete PWD field catalog against current FLAG screens.
2. Discover and certify the current ETA-9089 FLAG page/control map.
3. Add rules that complete OFLC seeds with internally consistent synthetic data.
4. Render clean FLAG drafts and attach artifact hashes and template geometry.
5. Add controlled scan/image transformations.
6. Import reviewed firm pairs as the real-document benchmark.
7. Export page/crop plus target-JSON examples for Qwen3-VL training.

The checked-in example uses fictional identities and is safe for tests and
documentation.  It is deliberately a `seed`, demonstrating what is known before
the form-completion rules and FLAG map are added.
