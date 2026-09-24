"""Application error types and their HTTP mapping.

Every error the frontend can see is an AppError with a stable `code` and a
message that is safe to show (no credentials, no stack traces).
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.utils.logging import get_request_id

logger = logging.getLogger("jev_eval.errors")


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# --- MySQL / schema ---
class DatabaseUnavailableError(AppError):
    status_code = 503
    code = "mysql_unavailable"


class DatabaseAuthError(AppError):
    status_code = 503
    code = "mysql_auth_failed"


class DatabaseNotFoundError(AppError):
    status_code = 503
    code = "mysql_database_not_found"


class EmptySchemaError(AppError):
    status_code = 503
    code = "empty_schema"


# --- Request validation against the live schema ---
class InvalidExpectedFieldError(AppError):
    status_code = 422
    code = "invalid_expected_field"


class NoCandidatesError(AppError):
    status_code = 422
    code = "no_candidate_fields"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class TestCasesError(AppError):
    __test__ = False  # not a pytest test class
    status_code = 500
    code = "invalid_test_cases"


# --- JEV ---
class JEVError(AppError):
    status_code = 502
    code = "jev_error"


class JEVNotConfiguredError(JEVError):
    status_code = 503
    code = "jev_not_configured"


class JEVAuthError(JEVError):
    status_code = 502
    code = "jev_auth_failed"


class JEVRequestError(JEVError):
    """The provider rejected the request (4xx other than auth/rate limit)."""

    status_code = 502
    code = "jev_request_rejected"


class JEVTimeoutError(JEVError):
    status_code = 504
    code = "jev_timeout"


class JEVUpstreamError(JEVError):
    """Transient failure (network, 429, 5xx) that persisted after retries."""

    status_code = 502
    code = "jev_upstream_error"


class JEVMalformedResponseError(JEVError):
    status_code = 502
    code = "jev_malformed_response"


def _error_body(code: str, message: str, details: dict | None = None) -> dict:
    body = {"error": {"code": code, "message": message, "request_id": get_request_id()}}
    if details:
        body["error"]["details"] = details
    return body


def register_error_handlers(app: FastAPI, *, debug_errors: bool = False) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        logger.warning("request_failed", extra={"error_code": exc.code, "error_message": exc.message})
        return JSONResponse(status_code=exc.status_code, content=_error_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(p) for p in err.get("loc", []) if p != "body"), "message": err.get("msg", "")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_body("validation_error", "Request validation failed.", {"errors": errors}),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception")
        message = f"{type(exc).__name__}: {exc}" if debug_errors else "Internal server error."
        return JSONResponse(status_code=500, content=_error_body("internal_error", message))
