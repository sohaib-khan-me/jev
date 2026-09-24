"""Manual check: send ONE real request to JEV (Cloudflare or OpenRouter) and show what came back.

    cd backend && source .venv/bin/activate
    python -m scripts.test_jev_connection ["Find students with CGPA above 3.5."]

Uses backend/.env. Reads the live MySQL schema (read-only) to build candidates.
The raw response is saved to backend/data/jev_last_raw_response.json so the
parser can be checked against JEV's real output. The API token is never printed.
"""

import json
import sys
import time

import httpx

from app.config import BACKEND_DIR, get_settings
from app.database.connection import create_mysql_engine
from app.services.candidate_service import CandidateService
from app.services.jev_service import build_jev_payload, parse_choice_response
from app.services.mysql_schema_service import MySQLSchemaService
from app.utils.errors import AppError


def main() -> int:
    campaign = sys.argv[1] if len(sys.argv) > 1 else "Find students with CGPA above 3.5."
    settings = get_settings()

    if not settings.jev_configured:
        print(f"JEV is not configured. {settings.jev_credential_hint}")
        return 1

    snapshot = MySQLSchemaService(create_mysql_engine(settings), settings).get_snapshot()
    candidates = CandidateService(settings.candidate_max_fields).generate(campaign, snapshot)
    values = dict(snapshot.column_values) if settings.jev_include_sample_values else None
    payload = build_jev_payload(campaign, candidates, snapshot.schema, settings.jev_request_model, values)

    # The Cloudflare URL contains the account ID, so only the host part is printed.
    print(f"Provider : {settings.jev_provider}")
    print(f"Endpoint : {settings.jev_endpoint.split('/accounts/')[0]}{'/accounts/<account id>/ai/run' if '/accounts/' in settings.jev_endpoint else ''}")
    print(f"Model    : {settings.jev_request_model}")
    print(f"Campaign : {campaign}")
    print(f"Candidates sent: {len(candidates)}")

    started = time.perf_counter()
    response = httpx.post(
        settings.jev_endpoint,
        json=payload,
        headers={"Authorization": f"Bearer {settings.jev_api_token.get_secret_value()}"},
        timeout=settings.jev_timeout_seconds,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    print(f"HTTP status: {response.status_code}   latency: {latency_ms:.0f} ms")

    try:
        raw = response.json()
    except ValueError:
        print("Response was not JSON:", response.text[:500])
        return 1

    out = BACKEND_DIR / "data" / "jev_last_raw_response.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"request": payload, "status": response.status_code, "response": raw}, indent=2))
    print(f"Raw request/response saved to {out}")

    if response.status_code >= 400:
        print(json.dumps(raw, indent=2)[:2000])
        return 1

    try:
        result = parse_choice_response(
            raw, {c.field for c in candidates}, latency_ms=latency_ms, attempts=1, source=settings.jev_provider
        )
    except AppError as exc:
        print(f"PARSER FAILED ({exc.code}): {exc.message}")
        print("Top-level keys:", list(raw))
        return 1

    print(f"Response model : {result.model}")
    print(f"Selected field : {result.selected_field}")
    print(f"Confidence     : {result.confidence}")
    print("Probabilities  :" if result.probabilities else f"Probabilities  : none ({result.probabilities_note})")
    for field, p in list(result.probabilities.items())[:10]:
        print(f"  {field:32s} {p:.4f}")
    print(f"Usage          : {result.usage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
