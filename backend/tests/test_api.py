from app.utils.errors import JEVTimeoutError
from tests.conftest import FakeJEVClient


def test_health_ok(make_client):
    body = make_client().get("/api/health").json()
    assert body == {
        "status": "ok",
        "mysql": "connected",
        "mysql_error": None,
        "database": "fast_jev_test",
        "jev_configured": False,
        "jev_mock_mode": False,
        "jev_provider": "cloudflare",
        "jev_model": "typesafe/jev",
    }


def test_health_degraded_when_mysql_down(make_client):
    body = make_client(mysql_up=False).get("/api/health").json()
    assert body["status"] == "degraded" and body["mysql"] == "unavailable"


def test_health_never_exposes_secrets(make_client, settings):
    text = make_client().get("/api/health").text
    assert "not-used" not in text  # the fixture's MySQL password


def test_schema_endpoints(make_client):
    client = make_client()
    schema = client.get("/api/schema").json()
    assert len(schema["tables"]) == 6
    assert "column_values" not in schema  # backend-only data stays backend-only
    assert client.post("/api/schema/refresh").status_code == 200


def test_schema_503_when_mysql_down(make_client):
    response = make_client(mysql_up=False).get("/api/schema")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "mysql_unavailable"


def test_evaluate_success(make_client):
    client = make_client(FakeJEVClient({"Find students with CGPA above 3.5.": "students.cgpa"}))
    body = client.post("/api/evaluate", json={"campaign": "Find students with CGPA above 3.5.", "expected_field": "students.cgpa"}).json()
    assert body["selected_field"] == "students.cgpa" and body["correct"] is True
    assert body["probabilities"]["students.cgpa"] == 0.9
    assert body["source"] == "cloudflare"


def test_evaluate_rejects_blank_campaign(make_client):
    response = make_client().post("/api/evaluate", json={"campaign": "   "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_evaluate_rejects_unknown_expected_field(make_client):
    response = make_client().post("/api/evaluate", json={"campaign": "x students", "expected_field": "students.nope"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_expected_field"


def test_evaluate_without_credentials_says_not_configured(make_client, settings, snapshot):
    from fastapi.testclient import TestClient

    from app.dependencies import build_container
    from app.main import create_app
    from tests.conftest import FakeSchemaService

    container = build_container(settings, schema_service=FakeSchemaService(snapshot))  # real factory, no creds
    response = TestClient(create_app(settings, container)).post("/api/evaluate", json={"campaign": "Find female students."})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "jev_not_configured"


def test_jev_timeout_maps_to_504(make_client):
    response = make_client(FakeJEVClient(error=JEVTimeoutError("JEV did not respond."))).post(
        "/api/evaluate", json={"campaign": "Find female students."}
    )
    assert response.status_code == 504 and response.json()["error"]["code"] == "jev_timeout"


def test_history_endpoints(make_client):
    client = make_client()
    created = client.post("/api/evaluate", json={"campaign": "Find female students."}).json()
    listing = client.get("/api/evaluations").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == created["id"]
    assert client.get(f"/api/evaluations/{created['id']}").json()["raw_response"] is not None
    assert client.get("/api/evaluations/missing").status_code == 404


def test_test_suite_endpoints(make_client):
    client = make_client()
    assert len(client.get("/api/tests").json()) >= 20
    assert client.get("/api/tests/runs/latest").json() is None
    run = client.post("/api/tests/run", json={"test_ids": ["TC001", "TC002"], "run_id": "ui-run-1"}).json()
    assert run["metrics"]["total_tests"] == 2
    client.post("/api/tests/run", json={"test_ids": ["TC003"], "run_id": "ui-run-1"})
    assert client.get("/api/tests/runs/ui-run-1").json()["metrics"]["total_tests"] == 3
    assert client.get("/api/tests/runs/latest").json()["metrics"]["run_id"] == "ui-run-1"


def test_run_all_without_body(make_client):
    body = make_client().post("/api/tests/run").json()
    assert body["metrics"]["total_tests"] >= 20


def test_unknown_test_id_is_404(make_client):
    assert make_client().post("/api/tests/run", json={"test_ids": ["NOPE"]}).status_code == 404


def test_cors_allows_only_frontend_origin(make_client):
    client = make_client()
    ok = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    bad = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


def test_request_id_header(make_client):
    assert make_client().get("/api/health").headers["X-Request-ID"]
