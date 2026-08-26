"""Versioned JSON contract for paired ETA-9141 and ETA-9089 records.

The contract deliberately separates the values printed on a form from their
provenance and visual evidence.  A seed made from OFLC disclosure data can be
completed by synthetic rules, rendered in FLAG, and later enriched with page
coordinates without changing its identity or field paths.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SCHEMA_VERSION = "casebase.perm-pwd-pair.v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceReference(StrictModel):
    """One source record used to construct the paired case."""

    source_id: str
    kind: Literal[
        "oflc_perm",
        "oflc_pw",
        "firm_document",
        "synthetic_rule",
        "human_review",
    ]
    table: str | None = None
    record_id: str | None = None
    source_file: str | None = None
    fiscal_year: str | None = None
    public_data: bool = False
    notes: str | None = None


class FieldSource(StrictModel):
    """How the ground-truth value for one JSON path was obtained."""

    kind: Literal[
        "oflc_perm",
        "oflc_pw",
        "shared_case_fact",
        "synthetic_rule",
        "firm_document",
        "deterministic_parser",
        "human_review",
    ]
    source_id: str | None = None
    source_field: str | None = None
    generator_rule: str | None = None
    transformation: str | None = None


class BoundingBox(StrictModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def ordered(self) -> "BoundingBox":
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("bounding box must have positive width and height")
        return self


class FieldEvidence(StrictModel):
    """Visual/text grounding added after a form has been rendered or reviewed."""

    page: int = Field(ge=1)
    quote: str | None = None
    bounding_box: BoundingBox | None = None
    extraction_method: Literal[
        "known_template_geometry",
        "pdf_text_layer",
        "ocr",
        "vlm",
        "human",
    ]
    quote_verified: bool = False


class FieldAnnotation(StrictModel):
    """Sidecar metadata keyed by a canonical form-data path."""

    state: Literal[
        "present",
        "blank",
        "not_applicable",
        "unreadable",
        "not_found",
        "conflicting",
    ] = "present"
    source: FieldSource
    evidence: FieldEvidence | None = None
    review_status: Literal[
        "unreviewed",
        "auto_validated",
        "human_verified",
        "needs_review",
    ] = "unreviewed"
    notes: str | None = None


class DocumentArtifact(StrictModel):
    filename: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    page_count: int | None = Field(default=None, ge=1)
    renderer: str | None = None
    rendering_seed: int | None = None
    augmentations: list[str] = Field(default_factory=list)


class DocumentMetadata(StrictModel):
    document_id: str
    form: Literal["ETA-9141", "ETA-9089"]
    form_edition: str
    stage: Literal["seed", "generated", "rendered", "reviewed"] = "seed"
    artifact_kind: Literal[
        "flag_draft",
        "determination",
        "filed",
        "certified",
        "correction",
        "training_render",
    ]
    source_type: Literal["synthetic", "semi_synthetic", "firm_real"]
    artifact: DocumentArtifact = Field(default_factory=DocumentArtifact)


class Address(StrictModel):
    address1: str | None = None
    address2: str | None = None
    city: str | None = None
    county: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = "United States"
    province: str | None = None


class PWDMeta(StrictModel):
    pwd_case_number: str | None = Field(
        default=None, pattern=r"^P-\d{3}-\d{5}-\d{6}$"
    )
    case_status: str | None = None
    received_date: date | None = None
    determination_date: date | None = None
    validity_from: date | None = None
    validity_to: date | None = None


class PWDEmployer(StrictModel):
    legal_business_name: str | None = None
    trade_name: str | None = None
    fein: str | None = Field(default=None, pattern=r"^\d{2}-?\d{7}$")
    naics_code: str | None = None
    address: Address = Field(default_factory=Address)


class PWDJobOffer(StrictModel):
    job_title: str | None = None
    job_duties: str | None = None
    worksite: Address = Field(default_factory=Address)
    travel_required: bool | None = None
    travel_details: str | None = None
    telecommuting_allowed: bool | None = None
    telecommuting_details: str | None = None


class PWDRequirementSet(StrictModel):
    education_level: str | None = None
    majors: str | None = None
    second_degree_required: bool | None = None
    training_required: bool | None = None
    training_months: int | None = Field(default=None, ge=0)
    training_field: str | None = None
    experience_required: bool | None = None
    experience_months: int | None = Field(default=None, ge=0)
    experience_occupation: str | None = None
    special_requirements_required: bool | None = None
    special_requirements_text: str | None = None
    special_requirement_items: list[str] = Field(default_factory=list)
    foreign_language_required: bool | None = None


class PWDDetermination(StrictModel):
    soc_code: str | None = None
    soc_title: str | None = None
    onet_code: str | None = None
    onet_title: str | None = None
    combination_soc_code: str | None = None
    combination_soc_title: str | None = None
    prevailing_wage: float | None = Field(default=None, ge=0)
    alternate_prevailing_wage: float | None = Field(default=None, ge=0)
    wage_unit: Literal["Hour", "Week", "Bi-Weekly", "Month", "Year"] | None = None
    wage_level: str | None = None
    wage_source: str | None = None
    survey_name: str | None = None
    bls_area: str | None = None


class PWDFormData(StrictModel):
    meta: PWDMeta = Field(default_factory=PWDMeta)
    employer: PWDEmployer = Field(default_factory=PWDEmployer)
    requestor_contact: dict[str, Any] = Field(default_factory=dict)
    attorney_agent: dict[str, Any] = Field(default_factory=dict)
    job_offer: PWDJobOffer = Field(default_factory=PWDJobOffer)
    primary_requirements: PWDRequirementSet = Field(default_factory=PWDRequirementSet)
    alternate_requirements_accepted: bool | None = None
    alternate_requirements: PWDRequirementSet | None = None
    determination: PWDDetermination = Field(default_factory=PWDDetermination)


class PERMMeta(StrictModel):
    perm_case_number: str | None = Field(
        default=None, pattern=r"^G-\d{3}-\d{5}-\d{6}$"
    )
    case_status: str | None = None
    received_date: date | None = None
    decision_date: date | None = None
    filing_date: date | None = None


class PERMFormData(StrictModel):
    """ETA-9089 sections use the existing canonical section names.

    Section dictionaries remain extensible while the FLAG selector inventory is
    being completed.  Their permitted fields are documented in
    ``app/perm_verify/form_9089_schema.json`` and can be made strict once the
    end-to-end FLAG map is certified.
    """

    meta: PERMMeta = Field(default_factory=PERMMeta)
    A_employer: dict[str, Any] = Field(default_factory=dict)
    B_poc: dict[str, Any] = Field(default_factory=dict)
    C_attorney_agent: dict[str, Any] = Field(default_factory=dict)
    D_foreign_worker_flags: dict[str, Any] = Field(default_factory=dict)
    E_job_wage: dict[str, Any] = Field(default_factory=dict)
    F_worksite: dict[str, Any] = Field(default_factory=dict)
    G_job_info: dict[str, Any] = Field(default_factory=dict)
    H_recruitment: dict[str, Any] = Field(default_factory=dict)
    I_attestations: dict[str, Any] = Field(default_factory=dict)
    J_preparer: dict[str, Any] = Field(default_factory=dict)
    appendix_A: dict[str, Any] = Field(default_factory=dict)
    appendix_B: dict[str, Any] = Field(default_factory=dict)
    appendix_C: dict[str, Any] = Field(default_factory=dict)
    appendix_D: dict[str, Any] = Field(default_factory=dict)


class PWDDocument(StrictModel):
    metadata: DocumentMetadata
    form_data: PWDFormData
    annotations: dict[str, FieldAnnotation] = Field(default_factory=dict)

    @model_validator(mode="after")
    def correct_form(self) -> "PWDDocument":
        if self.metadata.form != "ETA-9141":
            raise ValueError("PWD document metadata.form must be ETA-9141")
        return self


class PERMDocument(StrictModel):
    metadata: DocumentMetadata
    form_data: PERMFormData
    annotations: dict[str, FieldAnnotation] = Field(default_factory=dict)

    @model_validator(mode="after")
    def correct_form(self) -> "PERMDocument":
        if self.metadata.form != "ETA-9089":
            raise ValueError("PERM document metadata.form must be ETA-9089")
        return self


class ExpectedComparison(StrictModel):
    comparison_id: str
    pwd_path: str
    perm_path: str
    expected: Literal["match", "mismatch", "not_comparable"]
    rule: str
    notes: str | None = None


class PrivacyMetadata(StrictModel):
    classification: Literal["public", "synthetic", "confidential_firm"]
    contains_real_person_data: bool
    contains_real_employer_data: bool
    training_approved: bool
    redaction_notes: str | None = None


class SharedCaseFacts(StrictModel):
    """Disclosure facts that describe the case but may not be printed on both forms."""

    employer_name: str | None = None
    employer_fein: str | None = None
    job_title: str | None = None
    soc_code: str | None = None
    soc_title: str | None = None
    worksite_city: str | None = None
    worksite_state: str | None = None
    worksite_postal_code: str | None = None


class PermPwdPair(StrictModel):
    """One linked training case containing a PWD and its ETA-9089."""

    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    case_id: str
    created_at: datetime
    random_seed: int | None = None
    lifecycle_stage: Literal["seed", "generated", "rendered", "reviewed"] = "seed"
    privacy: PrivacyMetadata
    sources: list[SourceReference]
    shared_case_facts: SharedCaseFacts = Field(default_factory=SharedCaseFacts)
    shared_fact_annotations: dict[str, FieldAnnotation] = Field(default_factory=dict)
    pwd: PWDDocument
    perm: PERMDocument
    expected_comparisons: list[ExpectedComparison] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_linked_pwd_number(self) -> "PermPwdPair":
        pwd_number = self.pwd.form_data.meta.pwd_case_number
        perm_number = self.perm.form_data.E_job_wage.get("pwd_case_number")
        expects_match = any(
            item.pwd_path == "pwd.form_data.meta.pwd_case_number"
            and item.perm_path == "perm.form_data.E_job_wage.pwd_case_number"
            and item.expected == "match"
            for item in self.expected_comparisons
        )
        if expects_match and pwd_number and perm_number and pwd_number != perm_number:
            raise ValueError("paired PWD numbers differ despite an expected match")
        return self
