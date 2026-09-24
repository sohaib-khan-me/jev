"""Pydantic models shared by services and the HTTP API.

Three concepts are deliberately kept in separate fields and never merged:
  1. JEV selection      -> `selected_field`
  2. JEV certainty      -> `confidence` and `probabilities` (exactly as JEV returned them)
  3. Our correctness    -> `correct` (selected_field == expected_field, computed locally)
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------


class ForeignKeyRef(BaseModel):
    column: str
    references_table: str
    references_column: str
    constraint_name: str | None = None


class ColumnInfo(BaseModel):
    name: str
    type: str = Field(description="Base data type, e.g. 'int', 'varchar', 'decimal'.")
    column_type: str = Field(description="Full MySQL type, e.g. 'decimal(3,2)'.")
    nullable: bool
    primary_key: bool = False
    unique: bool = False
    auto_increment: bool = False
    foreign_key: ForeignKeyRef | None = None


class TableInfo(BaseModel):
    name: str
    row_count: int | None = Field(default=None, description="Exact COUNT(*), or null if it could not be read.")
    primary_key: list[str] = []
    columns: list[ColumnInfo]
    foreign_keys: list[ForeignKeyRef] = []


class Relationship(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    constraint_name: str | None = None

    @property
    def label(self) -> str:
        return f"{self.from_table}.{self.from_column} → {self.to_table}.{self.to_column}"


class AmbiguousColumnGroup(BaseModel):
    """Non-key columns that share a name across tables (e.g. students.city / campuses.city)."""

    column_name: str
    fields: list[str]


class DatabaseSchema(BaseModel):
    database: str
    discovered_at: datetime
    tables: list[TableInfo]
    relationships: list[Relationship]
    ambiguous_columns: list[AmbiguousColumnGroup] = []

    def field_ids(self) -> list[str]:
        return [f"{t.name}.{c.name}" for t in self.tables for c in t.columns]

    def get_table(self, name: str) -> TableInfo | None:
        return next((t for t in self.tables if t.name == name), None)


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


class Candidate(BaseModel):
    field: str = Field(description="Fully qualified identifier, always 'table.column'.")
    table: str
    column: str
    column_type: str
    is_key: bool = False
    score: float = Field(description="Deterministic ranking score. Never sent to JEV.")
    reasons: list[str] = []


# ---------------------------------------------------------------------------
# JEV
# ---------------------------------------------------------------------------

JEVSource = Literal["cloudflare", "openrouter", "mock"]


class JEVChoiceResult(BaseModel):
    """Normalized answer to one JEV `choice` question. Values are copied from JEV, never derived."""

    selected_field: str
    confidence: float | None = None
    probabilities: dict[str, float] = {}
    probabilities_note: str | None = Field(default=None, description="Why probabilities are empty, if they are.")
    model: str | None = None
    usage: dict[str, Any] | None = None
    raw_response: dict[str, Any]
    latency_ms: float = Field(description="Wall-clock time of the JEV call, including any retries.")
    attempts: int = 1
    source: JEVSource


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class EvaluateRequest(BaseModel):
    campaign: str = Field(min_length=1, max_length=1000, examples=["Find students with CGPA above 3.5."])
    expected_field: str | None = Field(default=None, examples=["students.cgpa"])

    @field_validator("campaign")
    @classmethod
    def campaign_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Campaign must not be empty.")
        return value

    @field_validator("expected_field")
    @classmethod
    def blank_expected_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


EvaluationStatus = Literal["ok", "error"]


class EvaluationResult(BaseModel):
    id: str
    created_at: datetime
    status: EvaluationStatus
    error: dict[str, str] | None = Field(default=None, description="{code, message} when status is 'error'.")

    campaign: str
    expected_field: str | None = None
    expected_fields: list[str] = Field(default=[], description="Only for multi-field test cases.")
    acceptable_alternatives: list[str] = Field(default=[], description="Known ambiguous alternatives (test cases only).")

    # 1. JEV selection
    selected_field: str | None = None
    # 2. JEV certainty (copied from JEV's response)
    confidence: float | None = None
    low_confidence: bool | None = None
    probabilities: dict[str, float] = {}
    probabilities_note: str | None = None
    # 3. Our local evaluation
    correct: bool | None = Field(default=None, description="selected == expected. Null when there is no single expected field.")
    matched_alternative: bool | None = None
    selected_in_expected_set: bool | None = Field(default=None, description="Multi-field cases only.")
    expected_in_candidates: bool | None = Field(
        default=None, description="False means candidate generation removed the expected field before JEV saw it."
    )
    ambiguity_notes: list[str] = []

    candidates: list[Candidate] = []
    latency_ms: float | None = None
    attempts: int | None = None
    model: str | None = None
    usage: dict[str, Any] | None = None
    source: JEVSource | None = None
    raw_response: dict[str, Any] | None = None

    test_case_id: str | None = None
    category: str | None = None
    run_id: str | None = None


class EvaluationSummary(BaseModel):
    id: str
    created_at: datetime
    status: EvaluationStatus
    campaign: str
    expected_field: str | None
    selected_field: str | None
    correct: bool | None
    confidence: float | None
    latency_ms: float | None
    source: JEVSource | None
    test_case_id: str | None
    category: str | None
    run_id: str | None


class EvaluationList(BaseModel):
    total: int
    items: list[EvaluationSummary]


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

TestCategory = Literal["easy", "medium", "hard", "relational", "multi_field"]


class TestCase(BaseModel):
    __test__ = False  # not a pytest test class

    id: str
    category: TestCategory
    campaign: str = Field(min_length=1)
    expected_field: str | None = None
    expected_fields: list[str] = []
    ambiguous_with: list[str] = Field(default=[], description="Defensible alternatives. Scored as incorrect but reported.")
    notes: str | None = None

    @model_validator(mode="after")
    def check_expectations(self) -> "TestCase":
        if self.category == "multi_field":
            if len(self.expected_fields) < 2 or self.expected_field:
                raise ValueError(f"{self.id}: multi_field cases need 2+ expected_fields and no expected_field.")
        elif not self.expected_field or self.expected_fields:
            raise ValueError(f"{self.id}: single-field cases need exactly one expected_field.")
        return self


class TestRunRequest(BaseModel):
    test_ids: list[str] | None = Field(default=None, description="Run only these IDs. Omit to run the whole suite.")
    run_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]{1,64}$",
        description="Group several calls into one run (the UI runs tests one by one to show progress).",
    )


class CategoryMetrics(BaseModel):
    total: int
    correct: int
    incorrect: int
    errors: int
    accuracy: float | None


class TestRunMetrics(BaseModel):
    run_id: str
    source: JEVSource | Literal["mixed"] | None
    total_tests: int
    # Single-field accuracy only (multi-field cases are excluded).
    scored: int = Field(description="Single-field tests that got a JEV answer.")
    correct: int
    incorrect: int
    errors: int
    accuracy: float | None = Field(description="POC field-selection accuracy = correct / scored.")
    matched_alternative: int = Field(description="Incorrect answers that picked a documented ambiguous alternative.")
    expected_in_candidates_rate: float | None
    average_confidence: float | None
    low_confidence_count: int
    average_latency_ms: float | None
    min_latency_ms: float | None
    max_latency_ms: float | None
    by_category: dict[str, CategoryMetrics]
    multi_field_total: int
    multi_field_selected_in_expected_set: int


class TestRunResponse(BaseModel):
    metrics: TestRunMetrics
    results: list[EvaluationResult]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    mysql: Literal["connected", "unavailable"]
    mysql_error: str | None = None
    database: str
    jev_configured: bool
    jev_mock_mode: bool
    jev_provider: str
    jev_model: str
