"""Read-only MySQL engine.

Read-only is enforced in three layers:
  1. The MySQL account (jev_reader) only has SELECT and SHOW VIEW grants.
  2. Every session is switched to READ ONLY mode right after connecting.
  3. The application code only ever issues SELECT statements.
"""

import logging

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import DBAPIError, OperationalError

from app.config import Settings
from app.utils.errors import AppError, DatabaseAuthError, DatabaseNotFoundError, DatabaseUnavailableError

logger = logging.getLogger("jev_eval.mysql")

# MySQL error codes we translate into friendly messages.
_ACCESS_DENIED = {1045, 1698}
_UNKNOWN_DATABASE = 1049
_CANNOT_CONNECT = {2002, 2003, 2005, 2006, 2013}


def create_mysql_engine(settings: Settings) -> Engine:
    engine = create_engine(
        settings.mysql_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=5,
        connect_args={
            "connect_timeout": settings.mysql_connect_timeout_seconds,
            "read_timeout": settings.mysql_read_timeout_seconds,
            "charset": "utf8mb4",
        },
    )

    @event.listens_for(engine, "connect")
    def _set_read_only(dbapi_connection, _connection_record) -> None:
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")

    return engine


def translate_db_error(exc: Exception, database: str) -> AppError:
    """Convert a driver error into a safe AppError (never includes the password)."""
    code = None
    if isinstance(exc, DBAPIError) and exc.orig is not None and getattr(exc.orig, "args", None):
        first = exc.orig.args[0]
        code = first if isinstance(first, int) else None

    logger.error("mysql_error", extra={"mysql_error_code": code, "error_type": type(exc).__name__})

    if code in _ACCESS_DENIED:
        return DatabaseAuthError("MySQL rejected the configured credentials. Check MYSQL_USER / MYSQL_PASSWORD in backend/.env.")
    if code == _UNKNOWN_DATABASE:
        return DatabaseNotFoundError(f"MySQL database '{database}' does not exist or is not visible to this user.")
    if code in _CANNOT_CONNECT or isinstance(exc, OperationalError):
        return DatabaseUnavailableError("Cannot reach MySQL. Check that the server is running and MYSQL_HOST/MYSQL_PORT are correct.")
    return DatabaseUnavailableError("MySQL query failed.")


def check_connection(engine: Engine, database: str) -> None:
    """Raise an AppError if MySQL cannot be queried."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except DBAPIError as exc:
        raise translate_db_error(exc, database) from exc
