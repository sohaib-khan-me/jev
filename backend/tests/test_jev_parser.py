import json

import httpx
import pytest

from app.config import Settings
from app.services.candidate_service import generate_candidates
from app.services.jev_service import (
    INSTRUCTIONS,
    QUESTION_NAME,
    HttpJEVClient,
    MockJEVClient,
    UnconfiguredJEVClient,
    build_jev_payload,
    create_jev_client,
    parse_choice_response,
)
from app.utils.errors import (
    JEVAuthError,
    JEVMalformedResponseError,
    JEVNotConfiguredError,
    JEVRequestError,
    JEVTimeoutError,
    JEVUpstreamError,
)
from tests.conftest import FIXTURES

ALLOWED = {"students.age", "students.cgpa", "students.semester", "enrollments.marks"}
TOKEN = "test-token-should-never-leak"


def parse(raw, allowed=ALLOWED):
    return parse_choice_response(raw, allowed, latency_ms=10, attempts=1, source="cloudflare")


# --- Request construction -------------------------------------------------


def test_payload_is_a_typed_choice_question(snapshot):
    cands = generate_candidates("Find students with CGPA above 3.5.", snapshot.schema, snapshot.column_values)
    payload = build_jev_payload("Find students with CGPA above 3.5.", cands, snapshot.schema, "typesafe/jev")
    question = payload["questions"][QUESTION_NAME]
    assert payload["model"] == "typesafe/jev"
    assert question["type"] == "choice"
    assert question["instructions"] == INSTRUCTIONS
    assert list(question["criteria"]) == [c.field for c in cands]
    assert payload["state"]["campaign"] == "Find students with CGPA above 3.5."
    assert "students.department_id → departments.department_id" in payload["state"]["relationships"]


def test_payload_never_contains_scores_or_expected_answers(snapshot):
    cands = generate_candidates("Find students with CGPA above 3.5.", snapshot.schema, snapshot.column_values)
    text = json.dumps(build_jev_payload("Find students with CGPA above 3.5.", cands, snapshot.schema, "m"))
    assert "expected" not in text and "score" not in text


def test_sample_values_only_when_provided(snapshot):
    cands = generate_candidates("Find female students.", snapshot.schema, snapshot.column_values)
    without = build_jev_payload("x", cands, snapshot.schema, "m")
    with_values = build_jev_payload("x", cands, snapshot.schema, "m", dict(snapshot.column_values))
    assert "example values" not in without["questions"][QUESTION_NAME]["criteria"]["students.gender"]
    assert "Female" in with_values["questions"][QUESTION_NAME]["criteria"]["students.gender"]


# --- Response parsing -----------------------------------------------------


def test_parses_documented_response(jev_response_fixture):
    result = parse(jev_response_fixture)
    assert result.selected_field == "students.cgpa"
    assert result.confidence == 0.81  # copied as-is; NOT the top probability (0.88)
    assert result.probabilities["students.cgpa"] == 0.88
    assert list(result.probabilities)[0] == "students.cgpa"  # sorted descending
    assert result.usage == {"input_tokens": 640, "output_tokens": 41}
    assert result.model == "jev-1.13.0"
    assert result.raw_response == jev_response_fixture


def test_parses_cloudflare_envelope(jev_response_fixture):
    wrapped = {"result": jev_response_fixture, "success": True, "errors": [], "messages": []}
    assert parse(wrapped).selected_field == "students.cgpa"


def test_envelope_failure_is_an_error():
    with pytest.raises(JEVRequestError, match="bad input"):
        parse({"success": False, "errors": [{"message": "bad input"}], "result": None})


def test_missing_confidence_is_null_not_invented(jev_response_fixture):
    del jev_response_fixture["answers"][QUESTION_NAME]["confidence"]
    assert parse(jev_response_fixture).confidence is None


def test_out_of_range_confidence_is_null(jev_response_fixture):
    jev_response_fixture["answers"][QUESTION_NAME]["confidence"] = 1.7
    assert parse(jev_response_fixture).confidence is None


def test_missing_probabilities_explained(jev_response_fixture):
    del jev_response_fixture["answers"][QUESTION_NAME]["probabilities"]
    result = parse(jev_response_fixture)
    assert result.probabilities == {}
    assert "did not include" in result.probabilities_note


def test_non_numeric_probabilities_dropped(jev_response_fixture):
    jev_response_fixture["answers"][QUESTION_NAME]["probabilities"] = {"students.cgpa": "high", "students.age": True}
    result = parse(jev_response_fixture)
    assert result.probabilities == {} and result.probabilities_note


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"answers": {}},
        {"answers": {QUESTION_NAME: "students.cgpa"}},
        {"answers": {QUESTION_NAME: {"type": "choice"}}},
        {"answers": {QUESTION_NAME: {"type": "score", "score": 1}}},
    ],
)
def test_malformed_responses_raise(raw):
    with pytest.raises(JEVMalformedResponseError):
        parse(raw)


def test_choice_outside_candidates_is_rejected(jev_response_fixture):
    jev_response_fixture["answers"][QUESTION_NAME]["choice"] = "students.password"
    with pytest.raises(JEVMalformedResponseError, match="not one of the candidate"):
        parse(jev_response_fixture)


# --- HTTP client ------------------------------------------------------------


def make_settings(**overrides) -> Settings:
    base = dict(_env_file=None, cloudflare_account_id="acct123", cloudflare_api_token=TOKEN, jev_timeout_seconds=1)
    return Settings(**(base | overrides))


def make_client(handler, **overrides):
    sleeps = []
    client = HttpJEVClient(
        make_settings(**overrides), http_client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append
    )
    return client, sleeps


@pytest.fixture
def cgpa_candidates(snapshot):
    return generate_candidates("Find students with CGPA above 3.5.", snapshot.schema, snapshot.column_values)


def test_client_posts_bearer_request(snapshot, cgpa_candidates, jev_response_fixture):
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=jev_response_fixture)

    client, _ = make_client(handler)
    result = client.choose("Find students with CGPA above 3.5.", cgpa_candidates, snapshot.schema)
    assert seen["url"] == "https://api.cloudflare.com/client/v4/accounts/acct123/ai/run"
    assert seen["auth"] == f"Bearer {TOKEN}"
    assert seen["body"]["model"] == "typesafe/jev"
    assert result.selected_field == "students.cgpa" and result.attempts == 1 and result.source == "cloudflare"


def test_auth_error_not_retried(snapshot, cgpa_candidates):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"errors": [{"message": "Authentication error"}]})

    client, _ = make_client(handler)
    with pytest.raises(JEVAuthError) as exc:
        client.choose("x", cgpa_candidates, snapshot.schema)
    assert len(calls) == 1
    assert TOKEN not in exc.value.message


def test_bad_request_not_retried(snapshot, cgpa_candidates):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"errors": [{"message": "invalid questions"}]})

    client, _ = make_client(handler)
    with pytest.raises(JEVRequestError, match="invalid questions"):
        client.choose("x", cgpa_candidates, snapshot.schema)
    assert len(calls) == 1


def test_transient_error_retried_with_backoff(snapshot, cgpa_candidates, jev_response_fixture):
    responses = iter([httpx.Response(503), httpx.Response(429), httpx.Response(200, json=jev_response_fixture)])
    client, sleeps = make_client(lambda request: next(responses))
    result = client.choose("x", cgpa_candidates, snapshot.schema)
    assert result.attempts == 3
    assert sleeps == [0.5, 1.0]


def test_retries_are_capped_at_two(snapshot, cgpa_candidates):
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    client, sleeps = make_client(handler)
    with pytest.raises(JEVTimeoutError):
        client.choose("x", cgpa_candidates, snapshot.schema)
    assert len(calls) == 3 and len(sleeps) == 2


def test_persistent_5xx_is_upstream_error(snapshot, cgpa_candidates):
    client, _ = make_client(lambda request: httpx.Response(500, json={"errors": [{"message": "boom"}]}), jev_max_retries=0)
    with pytest.raises(JEVUpstreamError, match="boom"):
        client.choose("x", cgpa_candidates, snapshot.schema)


def test_non_json_success_is_malformed(snapshot, cgpa_candidates):
    client, _ = make_client(lambda request: httpx.Response(200, text="<html>"))
    with pytest.raises(JEVMalformedResponseError):
        client.choose("x", cgpa_candidates, snapshot.schema)


def test_factory_picks_client_by_config():
    assert isinstance(create_jev_client(make_settings(jev_mock_mode=True)), MockJEVClient)
    assert isinstance(create_jev_client(make_settings(cloudflare_api_token="")), UnconfiguredJEVClient)
    assert isinstance(create_jev_client(make_settings()), HttpJEVClient)


def test_unconfigured_client_refuses(snapshot, cgpa_candidates):
    with pytest.raises(JEVNotConfiguredError):
        UnconfiguredJEVClient(make_settings(cloudflare_api_token="")).choose("x", cgpa_candidates, snapshot.schema)


def test_mock_client_is_labelled_and_uniform(snapshot, cgpa_candidates):
    result = MockJEVClient().choose("x", cgpa_candidates, snapshot.schema)
    assert result.source == "mock" and result.raw_response["mock"] is True
    assert len(set(result.probabilities.values())) == 1


def test_settings_repr_hides_token():
    assert TOKEN not in repr(make_settings())


# --- OpenRouter ---------------------------------------------------------------


def test_parses_real_openrouter_response():
    """Captured from POST https://openrouter.ai/api/alpha/decisions (not synthetic)."""
    raw = json.loads((FIXTURES / "openrouter_real_response.json").read_text())
    result = parse_choice_response(
        raw, {"students.cgpa", "students.age", "students.semester"}, latency_ms=1441, attempts=1, source="openrouter"
    )
    assert result.selected_field == "students.cgpa"
    assert result.confidence == 1.0  # integer 1 in the JSON, accepted as a probability
    assert result.probabilities == {"students.cgpa": 1.0, "students.semester": 0.0, "students.age": 0.0}
    assert result.model.startswith("typesafe/jev")
    assert "cost" in result.usage
    assert result.raw_response["provider"] == "TypeSafe"


def test_openrouter_request_shape(snapshot, cgpa_candidates, jev_response_fixture):
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=jev_response_fixture)

    client, _ = make_client(handler, jev_provider="openrouter", openrouter_api_key="or-key", cloudflare_api_token="")
    result = client.choose("Find students with CGPA above 3.5.", cgpa_candidates, snapshot.schema)
    assert seen["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert seen["auth"] == "Bearer or-key"
    assert seen["body"]["model"] == "~typesafe/jev-latest"
    assert result.source == "openrouter"


def test_openrouter_error_message_extracted(snapshot, cgpa_candidates):
    client, _ = make_client(
        lambda request: httpx.Response(400, json={"error": {"message": "Invalid model", "code": 400}}),
        jev_provider="openrouter",
        openrouter_api_key="or-key",
    )
    with pytest.raises(JEVRequestError, match="OpenRouter rejected the request .*Invalid model"):
        client.choose("x", cgpa_candidates, snapshot.schema)


def test_openrouter_configuration_is_independent_of_cloudflare():
    assert make_settings(jev_provider="openrouter", openrouter_api_key="k", cloudflare_api_token="").jev_configured
    unconfigured = make_settings(jev_provider="openrouter", openrouter_api_key="")
    assert not unconfigured.jev_configured
    assert "OPENROUTER_API_KEY" in unconfigured.jev_credential_hint
