"""Shared fixtures. No test here needs MySQL or Cloudflare credentials.

The schema fixture is built from information_schema-shaped rows that mirror the
live fast_jev_test database, and goes through the real build_schema() code.

tests/fixtures/jev_choice_response.json follows the response shape documented
for typesafe/jev on Cloudflare (answers -> {type, choice, confidence,
probabilities}, usage). Its numbers are illustrative test data, NOT a captured
JEV response.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import PROJECT_ROOT, Settings
from app.database.schema_inspector import SchemaSnapshot, build_schema
from app.dependencies import build_container
from app.main import create_app
from app.models.schemas import JEVChoiceResult
from app.services.jev_service import QUESTION_NAME, parse_choice_response
from app.utils.errors import DatabaseUnavailableError, JEVError

FIXTURES = Path(__file__).parent / "fixtures"

# (table, column, data_type, column_type, nullable, key, extra)
_COLUMNS = [
    ("universities", "university_id", "int", "int", "NO", "PRI", "auto_increment"),
    ("universities", "university_name", "varchar", "varchar(150)", "NO", "", ""),
    ("universities", "abbreviation", "varchar", "varchar(30)", "YES", "", ""),
    ("universities", "country", "varchar", "varchar(100)", "YES", "", ""),
    ("universities", "established_year", "int", "int", "YES", "", ""),
    ("campuses", "campus_id", "int", "int", "NO", "PRI", "auto_increment"),
    ("campuses", "university_id", "int", "int", "NO", "MUL", ""),
    ("campuses", "campus_name", "varchar", "varchar(100)", "NO", "", ""),
    ("campuses", "city", "varchar", "varchar(100)", "YES", "", ""),
    ("campuses", "province", "varchar", "varchar(100)", "YES", "", ""),
    ("campuses", "campus_type", "varchar", "varchar(50)", "YES", "", ""),
    ("departments", "department_id", "int", "int", "NO", "PRI", "auto_increment"),
    ("departments", "campus_id", "int", "int", "NO", "MUL", ""),
    ("departments", "department_name", "varchar", "varchar(100)", "NO", "", ""),
    ("departments", "department_code", "varchar", "varchar(20)", "YES", "", ""),
    ("departments", "degree_type", "varchar", "varchar(50)", "YES", "", ""),
    ("students", "student_id", "int", "int", "NO", "PRI", "auto_increment"),
    ("students", "department_id", "int", "int", "NO", "MUL", ""),
    ("students", "student_name", "varchar", "varchar(100)", "NO", "", ""),
    ("students", "email", "varchar", "varchar(150)", "YES", "UNI", ""),
    ("students", "gender", "varchar", "varchar(20)", "YES", "", ""),
    ("students", "age", "int", "int", "YES", "", ""),
    ("students", "city", "varchar", "varchar(100)", "YES", "", ""),
    ("students", "semester", "int", "int", "YES", "", ""),
    ("students", "admission_year", "int", "int", "YES", "", ""),
    ("students", "cgpa", "decimal", "decimal(3,2)", "YES", "", ""),
    ("students", "scholarship_status", "varchar", "varchar(50)", "YES", "", ""),
    ("students", "student_status", "varchar", "varchar(30)", "YES", "", ""),
    ("courses", "course_id", "int", "int", "NO", "PRI", "auto_increment"),
    ("courses", "department_id", "int", "int", "NO", "MUL", ""),
    ("courses", "course_code", "varchar", "varchar(20)", "YES", "UNI", ""),
    ("courses", "course_name", "varchar", "varchar(150)", "YES", "", ""),
    ("courses", "credit_hours", "int", "int", "YES", "", ""),
    ("courses", "course_level", "varchar", "varchar(50)", "YES", "", ""),
    ("courses", "course_type", "varchar", "varchar(50)", "YES", "", ""),
    ("enrollments", "enrollment_id", "int", "int", "NO", "PRI", "auto_increment"),
    ("enrollments", "student_id", "int", "int", "NO", "MUL", ""),
    ("enrollments", "course_id", "int", "int", "NO", "MUL", ""),
    ("enrollments", "semester_name", "varchar", "varchar(50)", "YES", "", ""),
    ("enrollments", "enrollment_year", "int", "int", "YES", "", ""),
    ("enrollments", "marks", "decimal", "decimal(5,2)", "YES", "", ""),
    ("enrollments", "grade", "varchar", "varchar(5)", "YES", "", ""),
    ("enrollments", "enrollment_status", "varchar", "varchar(30)", "YES", "", ""),
]

_FKS = [
    ("campuses", "university_id", "universities", "university_id", "campuses_ibfk_1"),
    ("courses", "department_id", "departments", "department_id", "courses_ibfk_1"),
    ("departments", "campus_id", "campuses", "campus_id", "departments_ibfk_1"),
    ("enrollments", "course_id", "courses", "course_id", "enrollments_ibfk_2"),
    ("enrollments", "student_id", "students", "student_id", "enrollments_ibfk_1"),
    ("students", "department_id", "departments", "department_id", "students_ibfk_1"),
]

ROW_COUNTS = {"universities": 1, "campuses": 5, "departments": 7, "students": 12, "courses": 10, "enrollments": 35}

COLUMN_VALUES = {
    "students.city": ("Peshawar", "Mardan", "Swabi", "Charsadda", "Islamabad", "Rawalpindi", "Lahore", "Karachi"),
    "campuses.city": ("Islamabad", "Lahore", "Karachi", "Peshawar", "Chiniot"),
    "campuses.campus_name": ("Islamabad Campus", "Lahore Campus", "Karachi Campus", "Peshawar Campus", "Chiniot-Faisalabad Campus"),
    "students.gender": ("Male", "Female"),
    "students.scholarship_status": ("No Scholarship", "Merit Scholarship", "Need Based"),
    "students.student_status": ("Active", "Graduating"),
    "courses.course_name": ("Programming Fundamentals", "Database Systems", "Machine Learning", "Deep Learning"),
    "departments.department_name": ("Computer Science", "Artificial Intelligence", "Software Engineering", "Data Science"),
    "enrollments.grade": ("A", "A-", "B+", "B", "C+"),
}


def column_rows() -> list[dict]:
    rows, positions = [], {}
    for table, col, dtype, ctype, nullable, key, extra in _COLUMNS:
        positions[table] = positions.get(table, 0) + 1
        rows.append(
            {
                "TABLE_NAME": table,
                "COLUMN_NAME": col,
                "ORDINAL_POSITION": positions[table],
                "DATA_TYPE": dtype,
                "COLUMN_TYPE": ctype,
                "IS_NULLABLE": nullable,
                "COLUMN_KEY": key,
                "EXTRA": extra,
            }
        )
    return rows


def fk_rows() -> list[dict]:
    keys = ("TABLE_NAME", "COLUMN_NAME", "REFERENCED_TABLE_NAME", "REFERENCED_COLUMN_NAME", "CONSTRAINT_NAME")
    return [dict(zip(keys, fk)) for fk in _FKS]


@pytest.fixture
def schema():
    return build_schema("fast_jev_test", column_rows(), fk_rows(), ROW_COUNTS)


@pytest.fixture
def snapshot(schema):
    return SchemaSnapshot(schema=schema, column_values=COLUMN_VALUES)


@pytest.fixture
def jev_response_fixture() -> dict:
    return json.loads((FIXTURES / "jev_choice_response.json").read_text())


class FakeSchemaService:
    def __init__(self, snapshot: SchemaSnapshot, *, mysql_up: bool = True) -> None:
        self._snapshot = snapshot
        self.mysql_up = mysql_up
        self.database = snapshot.schema.database

    def get_snapshot(self) -> SchemaSnapshot:
        if not self.mysql_up:
            raise DatabaseUnavailableError("Cannot reach MySQL.")
        return self._snapshot

    refresh = get_snapshot

    def check_connection(self) -> None:
        if not self.mysql_up:
            raise DatabaseUnavailableError("Cannot reach MySQL.")


class FakeJEVClient:
    """Answers with a scripted field; records every call so tests can inspect inputs."""

    source = "cloudflare"

    def __init__(self, answers: dict[str, str] | None = None, *, confidence: float = 0.9, error: JEVError | None = None):
        self.answers = answers or {}
        self.confidence = confidence
        self.error = error
        self.calls: list[dict] = []

    def choose(self, campaign, candidates, schema, column_values=None) -> JEVChoiceResult:
        self.calls.append({"campaign": campaign, "candidates": [c.field for c in candidates]})
        if self.error:
            raise self.error
        choice = self.answers.get(campaign, candidates[0].field)
        rest = (1 - self.confidence) / max(1, len(candidates) - 1)
        raw = {
            "model": "jev-test-fixture",
            "answers": {
                QUESTION_NAME: {
                    "type": "choice",
                    "choice": choice,
                    "confidence": self.confidence,
                    "probabilities": {c.field: (self.confidence if c.field == choice else rest) for c in candidates},
                }
            },
            "usage": {"input_tokens": 100, "output_tokens": 10},
        }
        return parse_choice_response(raw, {c.field for c in candidates}, latency_ms=123.4, attempts=1, source="cloudflare")


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        mysql_password="not-used",
        history_db_path=tmp_path / "history.sqlite3",
        test_cases_path=PROJECT_ROOT / "evaluation" / "test_cases.json",
        frontend_url="http://localhost:5173",
    )


@pytest.fixture
def make_client(settings, snapshot):
    def _make(jev_client=None, *, mysql_up: bool = True, settings_override: Settings | None = None) -> TestClient:
        s = settings_override or settings
        container = build_container(
            s, schema_service=FakeSchemaService(snapshot, mysql_up=mysql_up), jev_client=jev_client or FakeJEVClient()
        )
        return TestClient(create_app(s, container))

    return _make
