"""Dynamic schema discovery from MySQL's information_schema.

Nothing here knows about specific tables: every table, column and foreign key is
discovered at runtime. The module has two halves:

  * fetch_*()      -> run read-only SELECT queries and return plain rows
  * build_schema() -> pure function turning those rows into a DatabaseSchema
                      (unit-testable without a database)
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Connection, text

from app.models.schemas import (
    AmbiguousColumnGroup,
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyRef,
    Relationship,
    TableInfo,
)

TEXT_TYPES = {"char", "varchar", "tinytext", "text", "mediumtext", "enum", "set"}

_COLUMNS_SQL = text(
    """
    SELECT c.TABLE_NAME, c.COLUMN_NAME, c.ORDINAL_POSITION, c.DATA_TYPE, c.COLUMN_TYPE,
           c.IS_NULLABLE, c.COLUMN_KEY, c.EXTRA
    FROM information_schema.COLUMNS c
    JOIN information_schema.TABLES t
      ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
    WHERE c.TABLE_SCHEMA = :db AND t.TABLE_TYPE = 'BASE TABLE'
    ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
    """
)

_FOREIGN_KEYS_SQL = text(
    """
    SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME, CONSTRAINT_NAME
    FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = :db AND REFERENCED_TABLE_NAME IS NOT NULL
    ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION
    """
)


def quote_identifier(name: str) -> str:
    """Quote a MySQL identifier. Names come from information_schema, but we escape anyway."""
    return "`" + name.replace("`", "``") + "`"


@dataclass(frozen=True)
class SchemaSnapshot:
    """A discovered schema plus backend-only data used for candidate generation.

    `column_values` maps 'table.column' -> distinct values of low-cardinality text
    columns. It is used for matching campaign words locally and is NOT returned
    by the schema API.
    """

    schema: DatabaseSchema
    column_values: Mapping[str, tuple[str, ...]]


def fetch_column_rows(conn: Connection, database: str) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(_COLUMNS_SQL, {"db": database})]


def fetch_foreign_key_rows(conn: Connection, database: str) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(_FOREIGN_KEYS_SQL, {"db": database})]


def fetch_row_counts(conn: Connection, tables: Iterable[str]) -> dict[str, int]:
    # information_schema.TABLES.TABLE_ROWS is only an InnoDB estimate (it reported
    # 0 for a 1-row table here), so we use exact COUNT(*) queries.
    return {t: int(conn.execute(text(f"SELECT COUNT(*) FROM {quote_identifier(t)}")).scalar_one()) for t in tables}


def fetch_column_values(
    conn: Connection, schema: DatabaseSchema, *, max_distinct: int, max_rows: int
) -> dict[str, tuple[str, ...]]:
    """Distinct values of non-key text columns, skipped for large tables or high cardinality."""
    values: dict[str, tuple[str, ...]] = {}
    for table in schema.tables:
        if table.row_count is None or table.row_count > max_rows:
            continue
        for col in table.columns:
            if col.type not in TEXT_TYPES or col.primary_key or col.unique or col.foreign_key:
                continue
            sql = text(
                f"SELECT DISTINCT {quote_identifier(col.name)} FROM {quote_identifier(table.name)} "
                f"WHERE {quote_identifier(col.name)} IS NOT NULL LIMIT {max_distinct + 1}"
            )
            found = [str(v) for v in conn.execute(sql).scalars()]
            if len(found) <= max_distinct:
                values[f"{table.name}.{col.name}"] = tuple(found)
    return values


def build_schema(
    database: str,
    column_rows: list[dict],
    fk_rows: list[dict],
    row_counts: Mapping[str, int] | None = None,
    discovered_at: datetime | None = None,
) -> DatabaseSchema:
    """Normalize raw information_schema rows into a DatabaseSchema."""
    row_counts = row_counts or {}

    fks_by_table: dict[str, list[ForeignKeyRef]] = defaultdict(list)
    fk_lookup: dict[tuple[str, str], ForeignKeyRef] = {}
    relationships: list[Relationship] = []
    for row in fk_rows:
        fk = ForeignKeyRef(
            column=row["COLUMN_NAME"],
            references_table=row["REFERENCED_TABLE_NAME"],
            references_column=row["REFERENCED_COLUMN_NAME"],
            constraint_name=row.get("CONSTRAINT_NAME"),
        )
        fks_by_table[row["TABLE_NAME"]].append(fk)
        fk_lookup[(row["TABLE_NAME"], row["COLUMN_NAME"])] = fk
        relationships.append(
            Relationship(
                from_table=row["TABLE_NAME"],
                from_column=fk.column,
                to_table=fk.references_table,
                to_column=fk.references_column,
                constraint_name=fk.constraint_name,
            )
        )

    columns_by_table: dict[str, list[ColumnInfo]] = defaultdict(list)
    for row in sorted(column_rows, key=lambda r: (r["TABLE_NAME"], int(r["ORDINAL_POSITION"]))):
        table, name = row["TABLE_NAME"], row["COLUMN_NAME"]
        key = (row.get("COLUMN_KEY") or "").upper()
        columns_by_table[table].append(
            ColumnInfo(
                name=name,
                type=str(row["DATA_TYPE"]).lower(),
                column_type=str(row["COLUMN_TYPE"]).lower(),
                nullable=str(row["IS_NULLABLE"]).upper() == "YES",
                primary_key=key == "PRI",
                unique=key == "UNI",
                auto_increment="auto_increment" in (row.get("EXTRA") or "").lower(),
                foreign_key=fk_lookup.get((table, name)),
            )
        )

    tables = [
        TableInfo(
            name=table,
            row_count=row_counts.get(table),
            primary_key=[c.name for c in cols if c.primary_key],
            columns=cols,
            foreign_keys=fks_by_table.get(table, []),
        )
        for table, cols in sorted(columns_by_table.items())
    ]

    return DatabaseSchema(
        database=database,
        discovered_at=discovered_at or datetime.now(timezone.utc),
        tables=tables,
        relationships=relationships,
        ambiguous_columns=find_ambiguous_columns(tables),
    )


def find_ambiguous_columns(tables: list[TableInfo]) -> list[AmbiguousColumnGroup]:
    """Group non-key columns whose names appear in more than one table."""
    by_name: dict[str, list[str]] = defaultdict(list)
    for table in tables:
        for col in table.columns:
            if not (col.primary_key or col.foreign_key):
                by_name[col.name].append(f"{table.name}.{col.name}")
    return [AmbiguousColumnGroup(column_name=n, fields=f) for n, f in sorted(by_name.items()) if len(f) > 1]
