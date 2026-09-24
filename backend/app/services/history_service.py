"""Evaluation history in a local SQLite file (never in the MySQL source database).

Each row keeps a few indexed columns for listing plus the full EvaluationResult
as JSON, so nothing JEV returned is lost.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from app.models.schemas import EvaluationList, EvaluationResult, EvaluationSummary

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluations (
    id             TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    run_id         TEXT,
    test_case_id   TEXT,
    category       TEXT,
    source         TEXT,
    status         TEXT NOT NULL,
    campaign       TEXT NOT NULL,
    expected_field TEXT,
    selected_field TEXT,
    correct        INTEGER,
    confidence     REAL,
    latency_ms     REAL,
    payload_json   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evaluations_created ON evaluations (created_at);
CREATE INDEX IF NOT EXISTS idx_evaluations_run ON evaluations (run_id);
"""


class HistoryService:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        # A new connection per call keeps this safe across FastAPI's worker threads.
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, result: EvaluationResult) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """INSERT INTO evaluations (id, created_at, run_id, test_case_id, category, source, status,
                       campaign, expected_field, selected_field, correct, confidence, latency_ms, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.id,
                    result.created_at.isoformat(),
                    result.run_id,
                    result.test_case_id,
                    result.category,
                    result.source,
                    result.status,
                    result.campaign,
                    result.expected_field,
                    result.selected_field,
                    None if result.correct is None else int(result.correct),
                    result.confidence,
                    result.latency_ms,
                    result.model_dump_json(),
                ),
            )

    def get(self, evaluation_id: str) -> EvaluationResult | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT payload_json FROM evaluations WHERE id = ?", (evaluation_id,)).fetchone()
        return EvaluationResult.model_validate_json(row["payload_json"]) if row else None

    def list_recent(self, *, limit: int = 50, offset: int = 0) -> EvaluationList:
        with closing(self._connect()) as conn:
            total = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
            rows = conn.execute(
                """SELECT id, created_at, status, campaign, expected_field, selected_field, correct, confidence,
                          latency_ms, source, test_case_id, category, run_id
                   FROM evaluations ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        items = [
            EvaluationSummary(**{**dict(r), "correct": None if r["correct"] is None else bool(r["correct"])})
            for r in rows
        ]
        return EvaluationList(total=total, items=items)

    def get_run(self, run_id: str) -> list[EvaluationResult]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM evaluations WHERE run_id = ? ORDER BY created_at", (run_id,)
            ).fetchall()
        return [EvaluationResult.model_validate_json(r["payload_json"]) for r in rows]

    def latest_run_id(self) -> str | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT run_id FROM evaluations WHERE run_id IS NOT NULL ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return row["run_id"] if row else None
