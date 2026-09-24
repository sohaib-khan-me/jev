"""Discovers and caches the MySQL schema.

The cache lives on this service instance (created once per app), not in a
module-level global. `refresh()` replaces it atomically.
"""

import logging
import threading
import time

from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError

from app.config import Settings
from app.database import schema_inspector as inspector
from app.database.connection import check_connection, translate_db_error
from app.database.schema_inspector import SchemaSnapshot
from app.utils.errors import EmptySchemaError

logger = logging.getLogger("jev_eval.schema")


class MySQLSchemaService:
    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings
        self._lock = threading.Lock()
        self._snapshot: SchemaSnapshot | None = None

    @property
    def database(self) -> str:
        return self._settings.mysql_database

    def get_snapshot(self) -> SchemaSnapshot:
        with self._lock:
            if self._snapshot is None:
                self._snapshot = self._discover()
            return self._snapshot

    def refresh(self) -> SchemaSnapshot:
        snapshot = self._discover()
        with self._lock:
            self._snapshot = snapshot
        return snapshot

    def check_connection(self) -> None:
        check_connection(self._engine, self.database)

    def _discover(self) -> SchemaSnapshot:
        started = time.perf_counter()
        db = self.database
        try:
            with self._engine.connect() as conn:
                column_rows = inspector.fetch_column_rows(conn, db)
                if not column_rows:
                    raise EmptySchemaError(f"Database '{db}' has no tables visible to user '{self._settings.mysql_user}'.")
                fk_rows = inspector.fetch_foreign_key_rows(conn, db)
                tables = sorted({r["TABLE_NAME"] for r in column_rows})
                counts = inspector.fetch_row_counts(conn, tables)
                schema = inspector.build_schema(db, column_rows, fk_rows, counts)
                values = inspector.fetch_column_values(
                    conn,
                    schema,
                    max_distinct=self._settings.value_scan_max_distinct,
                    max_rows=self._settings.value_scan_max_rows,
                )
        except DBAPIError as exc:
            raise translate_db_error(exc, db) from exc

        logger.info(
            "schema_discovered",
            extra={
                "database": db,
                "tables": len(schema.tables),
                "relationships": len(schema.relationships),
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return SchemaSnapshot(schema=schema, column_values=values)
