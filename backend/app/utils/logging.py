"""Structured (one JSON object per line) logging with a per-request ID.

Use it like normal logging and pass structured fields through `extra`:

    logger.info("jev_call_succeeded", extra={"latency_ms": 412, "selected_field": "students.cgpa"})
"""

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else came from `extra=`.
_STANDARD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_request_id(request_id: str | None):
    return _request_id.set(request_id)


def reset_request_id(token) -> None:
    _request_id.reset(token)


def get_request_id() -> str | None:
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        request_id = get_request_id()
        if request_id:
            entry["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("jev_eval")
    root.handlers = [handler]
    root.setLevel(level.upper())
    root.propagate = False
