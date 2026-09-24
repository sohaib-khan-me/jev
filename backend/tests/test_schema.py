import pytest
from sqlalchemy import text

from app.config import Settings
from app.database.schema_inspector import build_schema, quote_identifier
from tests.conftest import column_rows, fk_rows


def test_discovers_all_tables_sorted(schema):
    assert [t.name for t in schema.tables] == sorted(
        ["universities", "campuses", "departments", "students", "courses", "enrollments"]
    )


def test_columns_keep_ordinal_order_and_types(schema):
    students = schema.get_table("students")
    assert [c.name for c in students.columns][:3] == ["student_id", "department_id", "student_name"]
    cgpa = next(c for c in students.columns if c.name == "cgpa")
    assert (cgpa.type, cgpa.column_type, cgpa.nullable) == ("decimal", "decimal(3,2)", True)


def test_primary_keys_detected(schema):
    for table in schema.tables:
        assert len(table.primary_key) == 1
    student_id = schema.get_table("students").columns[0]
    assert student_id.primary_key and student_id.auto_increment and not student_id.nullable


def test_unique_columns_detected(schema):
    email = next(c for c in schema.get_table("students").columns if c.name == "email")
    assert email.unique and not email.primary_key


def test_foreign_keys_detected(schema):
    enrollments = schema.get_table("enrollments")
    refs = {(fk.column, fk.references_table, fk.references_column) for fk in enrollments.foreign_keys}
    assert refs == {("student_id", "students", "student_id"), ("course_id", "courses", "course_id")}
    course_id = next(c for c in enrollments.columns if c.name == "course_id")
    assert course_id.foreign_key.references_table == "courses"


def test_relationships_have_readable_labels(schema):
    labels = {r.label for r in schema.relationships}
    assert "students.department_id → departments.department_id" in labels
    assert len(schema.relationships) == 6


def test_ambiguous_columns_ignore_keys(schema):
    groups = {g.column_name: g.fields for g in schema.ambiguous_columns}
    assert groups == {"city": ["campuses.city", "students.city"]}


def test_row_counts_attached(schema):
    assert schema.get_table("enrollments").row_count == 35


def test_new_table_is_picked_up_without_code_changes():
    rows = column_rows() + [
        {"TABLE_NAME": "clubs", "COLUMN_NAME": "club_id", "ORDINAL_POSITION": 1, "DATA_TYPE": "int",
         "COLUMN_TYPE": "int", "IS_NULLABLE": "NO", "COLUMN_KEY": "PRI", "EXTRA": "auto_increment"},
    ]
    schema = build_schema("db", rows, fk_rows())
    assert "clubs" in [t.name for t in schema.tables]
    assert "clubs.club_id" in schema.field_ids()


def test_empty_rows_build_empty_schema():
    schema = build_schema("db", [], [])
    assert schema.tables == [] and schema.relationships == []


def test_quote_identifier_escapes_backticks():
    assert quote_identifier("students") == "`students`"
    assert quote_identifier("we`ird") == "`we``ird`"


# --- Optional live check (read-only). Skipped when MySQL is not reachable. ---


@pytest.fixture(scope="module")
def live_engine():
    from app.database.connection import create_mysql_engine

    settings = Settings()
    engine = create_mysql_engine(settings)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("MySQL not reachable with backend/.env credentials")
    yield engine, settings
    engine.dispose()


@pytest.mark.mysql
def test_live_schema_discovery(live_engine):
    from app.services.mysql_schema_service import MySQLSchemaService

    engine, settings = live_engine
    snapshot = MySQLSchemaService(engine, settings).get_snapshot()
    assert snapshot.schema.database == settings.mysql_database
    assert len(snapshot.schema.tables) >= 1
    assert all(t.row_count is not None for t in snapshot.schema.tables)


@pytest.mark.mysql
def test_live_session_is_read_only(live_engine):
    engine, _ = live_engine
    with engine.connect() as conn:
        assert conn.execute(text("SELECT @@session.transaction_read_only")).scalar_one() == 1
