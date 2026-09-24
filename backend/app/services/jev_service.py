"""JEV (TypeSafe's decision model) integration.

This is the only module that knows about JEV providers. The rest of the app uses
the `JEVClient` protocol:

    result = client.choose(campaign, candidates, schema)   # -> JEVChoiceResult

Both supported providers accept the same TypeSafe wire format:

    Cloudflare : POST {base}/accounts/{account_id}/ai/run   model "typesafe/jev"
    OpenRouter : POST {base}/alpha/decisions                model "~typesafe/jev-latest"

    {"model": "...",
     "state": {...},
     "questions": {"audience_field": {"type": "choice", "instructions": "...",
                                      "criteria": {"students.cgpa": "description", ...}}}}

    -> {"model": "jev-1.13.0",
        "answers": {"audience_field": {"type": "choice", "choice": "students.cgpa",
                                       "confidence": 0.8, "probabilities": {...}}},
        "usage": {"input_tokens": 426, "output_tokens": 73}}

A real OpenRouter response (tests/fixtures/openrouter_real_response.json) is
unwrapped and also carries "id", "provider" and usage.cost. Cloudflare's REST
API often wraps results as {"result": ..., "success": true}, so the parser
accepts both shapes.
"""

import logging
import math
import time
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.models.schemas import Candidate, DatabaseSchema, JEVChoiceResult
from app.utils.errors import (
    JEVAuthError,
    JEVMalformedResponseError,
    JEVNotConfiguredError,
    JEVRequestError,
    JEVTimeoutError,
    JEVUpstreamError,
)

logger = logging.getLogger("jev_eval.jev")

QUESTION_NAME = "audience_field"
INSTRUCTIONS = (
    "Identify the single database field that most directly represents the audience "
    "condition described by the campaign."
)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_BACKOFF_BASE_SECONDS = 0.5


# ---------------------------------------------------------------------------
# Request construction (pure, unit-tested)
# ---------------------------------------------------------------------------


def describe_candidate(candidate: Candidate, schema: DatabaseSchema, sample_values: tuple[str, ...] = ()) -> str:
    table = schema.get_table(candidate.table)
    column = next((c for c in table.columns if c.name == candidate.column), None) if table else None
    parts = [f"Column '{candidate.column}' of table '{candidate.table}', type {candidate.column_type}"]
    if column is not None:
        if column.primary_key:
            parts.append("primary key")
        if column.foreign_key:
            parts.append(f"foreign key to {column.foreign_key.references_table}.{column.foreign_key.references_column}")
    if sample_values:
        parts.append("example values: " + ", ".join(sample_values[:10]))
    return "; ".join(parts) + "."


def build_state(campaign: str, candidates: list[Candidate], schema: DatabaseSchema) -> dict[str, Any]:
    """Campaign + schema context. The expected field is never an input here."""
    tables_in_play = {c.table for c in candidates}
    tables = {
        t.name: [f"{c.name} ({c.column_type}{', PK' if c.primary_key else ''}{', FK' if c.foreign_key else ''})" for c in t.columns]
        for t in schema.tables
        if t.name in tables_in_play
    }
    relationships = [
        r.label for r in schema.relationships if r.from_table in tables_in_play or r.to_table in tables_in_play
    ]
    return {
        "campaign": campaign,
        "task": "Audience targeting: decide which database field the campaign's audience condition filters on.",
        "database": schema.database,
        "tables": tables,
        "relationships": relationships,
    }


def build_jev_payload(
    campaign: str,
    candidates: list[Candidate],
    schema: DatabaseSchema,
    model: str,
    column_values: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    column_values = column_values or {}
    criteria = {c.field: describe_candidate(c, schema, column_values.get(c.field, ())) for c in candidates}
    return {
        "model": model,
        "state": build_state(campaign, candidates, schema),
        "questions": {QUESTION_NAME: {"type": "choice", "instructions": INSTRUCTIONS, "criteria": criteria}},
    }


# ---------------------------------------------------------------------------
# Response parsing (pure, unit-tested)
# ---------------------------------------------------------------------------


def _as_probability(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and 0.0 <= value <= 1.0 else None


def unwrap_envelope(raw: dict[str, Any]) -> dict[str, Any]:
    """Return the model output, whether or not Cloudflare wrapped it in {"result": ...}."""
    if "answers" in raw:
        return raw
    if raw.get("success") is False:
        raise JEVRequestError(f"Provider reported failure: {_error_message(raw)}")
    result = raw.get("result")
    if isinstance(result, dict) and "answers" in result:
        return result
    raise JEVMalformedResponseError("JEV response has no 'answers' object.")


def parse_choice_response(
    raw: dict[str, Any],
    allowed_fields: set[str],
    *,
    latency_ms: float,
    attempts: int,
    source: str,
) -> JEVChoiceResult:
    if not isinstance(raw, dict):
        raise JEVMalformedResponseError("JEV response is not a JSON object.")
    body = unwrap_envelope(raw)

    answers = body.get("answers")
    answer = answers.get(QUESTION_NAME) if isinstance(answers, dict) else None
    if not isinstance(answer, dict):
        raise JEVMalformedResponseError(f"JEV response has no answer for question '{QUESTION_NAME}'.")
    if answer.get("type") not in (None, "choice"):
        raise JEVMalformedResponseError(f"Expected a 'choice' answer, got type '{answer.get('type')}'.")

    choice = answer.get("choice")
    if not isinstance(choice, str) or not choice:
        raise JEVMalformedResponseError("JEV answer has no 'choice' value.")
    if choice not in allowed_fields:
        raise JEVMalformedResponseError(f"JEV chose '{choice}', which was not one of the candidate fields.")

    probabilities: dict[str, float] = {}
    note = None
    raw_probs = answer.get("probabilities")
    if isinstance(raw_probs, dict):
        for key, value in raw_probs.items():
            p = _as_probability(value)
            if p is not None:
                probabilities[str(key)] = p
        if not probabilities:
            note = "JEV returned a 'probabilities' object without valid numeric values."
    else:
        note = "JEV response did not include a 'probabilities' object for this answer."

    usage = body.get("usage")
    return JEVChoiceResult(
        selected_field=choice,
        confidence=_as_probability(answer.get("confidence")),
        probabilities=dict(sorted(probabilities.items(), key=lambda kv: -kv[1])),
        probabilities_note=note,
        model=body.get("model") if isinstance(body.get("model"), str) else None,
        usage=usage if isinstance(usage, dict) else None,
        raw_response=raw,
        latency_ms=round(latency_ms, 1),
        attempts=attempts,
        source=source,
    )


def _error_message(body: Any) -> str:
    """Error text from Cloudflare ({"errors": [...]}) or OpenRouter ({"error": {"message": ...}})."""
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            msgs = [str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors]
            return "; ".join(msgs)[:500]
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:500]
        if isinstance(error, str):
            return error[:500]
    return "no error details returned"


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


class JEVClient(Protocol):
    source: str

    def choose(
        self,
        campaign: str,
        candidates: list[Candidate],
        schema: DatabaseSchema,
        column_values: dict[str, tuple[str, ...]] | None = None,
    ) -> JEVChoiceResult: ...


class HttpJEVClient:
    """Calls JEV over HTTP through the configured provider (Cloudflare or OpenRouter)."""

    def __init__(self, settings: Settings, http_client: httpx.Client | None = None, sleep=time.sleep) -> None:
        if not settings.jev_configured:
            raise JEVNotConfiguredError(f"JEV is not configured. {settings.jev_credential_hint}")
        self.source = settings.jev_provider
        self._provider_name = "OpenRouter" if settings.jev_provider == "openrouter" else "Cloudflare"
        self._settings = settings
        self._http = http_client or httpx.Client(timeout=httpx.Timeout(settings.jev_timeout_seconds, connect=5.0))
        self._sleep = sleep

    def choose(self, campaign, candidates, schema, column_values=None) -> JEVChoiceResult:
        values = column_values if self._settings.jev_include_sample_values else None
        payload = build_jev_payload(campaign, candidates, schema, self._settings.jev_request_model, values)
        raw, latency_ms, attempts = self._post_with_retries(payload)
        return parse_choice_response(
            raw, {c.field for c in candidates}, latency_ms=latency_ms, attempts=attempts, source=self.source
        )

    def _post_with_retries(self, payload: dict) -> tuple[dict, float, int]:
        headers = {"Authorization": f"Bearer {self._settings.jev_api_token.get_secret_value()}"}
        name = self._provider_name
        max_attempts = 1 + self._settings.jev_max_retries
        started = time.perf_counter()
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = self._http.post(self._settings.jev_endpoint, json=payload, headers=headers)
            except httpx.TimeoutException:
                last_error = JEVTimeoutError(f"JEV did not respond within {self._settings.jev_timeout_seconds}s.")
            except httpx.TransportError as exc:
                last_error = JEVUpstreamError(f"Network error calling {name}: {type(exc).__name__}.")
            else:
                status = response.status_code
                if status in (401, 403):
                    raise JEVAuthError(f"{name} rejected the API key. {self._settings.jev_credential_hint}")
                if status in _RETRYABLE_STATUS:
                    last_error = JEVUpstreamError(f"{name} returned HTTP {status}: {_error_message(_safe_json(response))}")
                elif status >= 400:
                    raise JEVRequestError(f"{name} rejected the request (HTTP {status}): {_error_message(_safe_json(response))}")
                else:
                    body = _safe_json(response)
                    if body is None:
                        raise JEVMalformedResponseError(f"{name} returned a non-JSON response.")
                    return body, (time.perf_counter() - started) * 1000, attempt

            if attempt < max_attempts:
                delay = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.warning("jev_retry", extra={"attempt": attempt, "delay_s": delay, "reason": str(last_error)})
                self._sleep(delay)

        assert last_error is not None
        raise last_error


def _safe_json(response: httpx.Response) -> dict | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


class MockJEVClient:
    """Development-only stand-in. Its output is obviously synthetic and labelled 'mock'.

    It always picks the first candidate (schema order) with a uniform distribution,
    so it can never be mistaken for a real JEV judgement.
    """

    source = "mock"
    MODEL = "MOCK-not-jev"

    def choose(self, campaign, candidates, schema, column_values=None) -> JEVChoiceResult:
        started = time.perf_counter()
        n = len(candidates)
        uniform = round(1 / n, 6)
        raw = {
            "model": self.MODEL,
            "mock": True,
            "answers": {
                QUESTION_NAME: {
                    "type": "choice",
                    "choice": candidates[0].field,
                    "confidence": uniform,
                    "probabilities": {c.field: uniform for c in candidates},
                }
            },
            "usage": None,
        }
        return parse_choice_response(
            raw,
            {c.field for c in candidates},
            latency_ms=(time.perf_counter() - started) * 1000,
            attempts=1,
            source=self.source,
        )


class UnconfiguredJEVClient:
    """Used when credentials are missing and mock mode is off. Always refuses."""

    def __init__(self, settings: Settings) -> None:
        self.source = settings.jev_provider
        self._hint = settings.jev_credential_hint

    def choose(self, campaign, candidates, schema, column_values=None) -> JEVChoiceResult:
        raise JEVNotConfiguredError(f"JEV is not configured. {self._hint}")


def create_jev_client(settings: Settings) -> JEVClient:
    if settings.jev_mock_mode:
        logger.warning("jev_mock_mode_enabled")
        return MockJEVClient()
    if not settings.jev_configured:
        return UnconfiguredJEVClient(settings)
    return HttpJEVClient(settings)
