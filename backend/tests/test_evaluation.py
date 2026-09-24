import pytest

from app.models.schemas import EvaluationResult, TestCase
from app.services.candidate_service import CandidateService
from app.services.evaluation_service import EvaluationService
from app.services.history_service import HistoryService
from app.services.suite_service import TestSuiteService, compute_metrics, load_test_cases
from app.utils.errors import InvalidExpectedFieldError, JEVNotConfiguredError, JEVTimeoutError, TestCasesError
from tests.conftest import FakeJEVClient, FakeSchemaService


@pytest.fixture
def build(settings, snapshot):
    def _build(jev):
        history = HistoryService(settings.history_db_path)
        service = EvaluationService(FakeSchemaService(snapshot), CandidateService(25), jev, history, settings)
        return service, history

    return _build


def test_correct_when_selection_matches(build):
    service, _ = build(FakeJEVClient({"Find female students.": "students.gender"}))
    result = service.evaluate("Find female students.", "students.gender")
    assert result.correct is True and result.status == "ok"
    assert result.expected_in_candidates is True


def test_confidence_does_not_decide_correctness(build):
    service, _ = build(FakeJEVClient({"Find female students.": "students.city"}, confidence=0.99))
    result = service.evaluate("Find female students.", "students.gender")
    assert result.confidence == 0.99 and result.correct is False


def test_expected_field_is_not_sent_to_jev(build):
    jev = FakeJEVClient()
    service, _ = build(jev)
    service.evaluate("Target younger students.", "students.age")
    assert jev.calls == [{"campaign": "Target younger students.", "candidates": jev.calls[0]["candidates"]}]


def test_no_expected_field_means_no_verdict(build):
    service, _ = build(FakeJEVClient())
    assert service.evaluate("Find female students.").correct is None


def test_invalid_expected_field_rejected_before_calling_jev(build):
    jev = FakeJEVClient()
    service, _ = build(jev)
    with pytest.raises(InvalidExpectedFieldError):
        service.evaluate("Find female students.", "students.favourite_colour")
    assert jev.calls == []


def test_matched_alternative_flagged(build):
    case = TestCase(id="T", category="easy", campaign="Find students from Peshawar.",
                    expected_field="students.city", ambiguous_with=["campuses.city"])
    service, _ = build(FakeJEVClient({case.campaign: "campuses.city"}))
    result = service.evaluate(case.campaign, case.expected_field, test_case=case)
    assert result.correct is False and result.matched_alternative is True
    assert any("students.city" in n for n in result.ambiguity_notes)


def test_low_confidence_flagged(build):
    service, _ = build(FakeJEVClient(confidence=0.2))
    assert service.evaluate("Target younger students.").low_confidence is True


def test_jev_error_saved_to_history_then_raised(build):
    service, history = build(FakeJEVClient(error=JEVTimeoutError("slow")))
    with pytest.raises(JEVTimeoutError):
        service.evaluate("Find female students.", "students.gender")
    saved = history.list_recent().items
    assert len(saved) == 1 and saved[0].status == "error" and saved[0].selected_field is None


def test_history_round_trip(build):
    service, history = build(FakeJEVClient())
    result = service.evaluate("Find female students.", "students.gender")
    assert history.get(result.id) == result
    assert history.list_recent().total == 1


# --- Metrics --------------------------------------------------------------


def _result(i, category, correct=None, status="ok", confidence=0.8, latency=100.0, **kw):
    from datetime import datetime, timezone

    return EvaluationResult(
        id=str(i), created_at=datetime.now(timezone.utc), status=status, campaign="c", category=category,
        correct=correct, confidence=confidence if status == "ok" else None,
        latency_ms=latency if status == "ok" else None, source="cloudflare", **kw,
    )


def test_metrics_exclude_multi_field_and_errors_from_accuracy():
    results = [
        _result(1, "easy", True, expected_in_candidates=True),
        _result(2, "easy", False, matched_alternative=True, expected_in_candidates=True),
        _result(3, "hard", True, latency=300.0, expected_in_candidates=True),
        _result(4, "hard", status="error", expected_in_candidates=False),
        _result(5, "multi_field", selected_in_expected_set=True),
    ]
    m = compute_metrics("run1", results)
    assert (m.total_tests, m.scored, m.correct, m.incorrect, m.errors) == (5, 3, 2, 1, 1)
    assert m.accuracy == round(2 / 3, 4)
    assert m.matched_alternative == 1
    assert m.multi_field_total == 1 and m.multi_field_selected_in_expected_set == 1
    assert m.by_category["hard"].errors == 1 and m.by_category["hard"].accuracy == 1.0
    assert m.expected_in_candidates_rate == 0.75
    assert (m.min_latency_ms, m.max_latency_ms) == (100.0, 300.0)
    assert m.average_confidence == 0.8


def test_metrics_with_no_answers_are_null_not_zero():
    m = compute_metrics("r", [_result(1, "easy", status="error")])
    assert m.accuracy is None and m.average_confidence is None and m.average_latency_ms is None


# --- Test cases & suite ---------------------------------------------------


def test_shipped_test_cases_are_valid_against_schema(settings, schema):
    cases = load_test_cases(settings.test_cases_path)
    assert len(cases) >= 20
    assert {"easy", "medium", "hard", "relational", "multi_field"} == {c.category for c in cases}
    fields = set(schema.field_ids())
    for case in cases:
        for f in [case.expected_field, *case.expected_fields, *case.ambiguous_with]:
            assert f is None or f in fields, f"{case.id}: {f}"


def test_invalid_test_case_file_rejected(tmp_path):
    bad = tmp_path / "cases.json"
    bad.write_text('[{"id": "X", "category": "easy", "campaign": "c"}]')
    with pytest.raises(TestCasesError):
        load_test_cases(bad)


def test_suite_runs_sequentially_and_scores(build, settings):
    jev = FakeJEVClient({"Find female students.": "students.gender"})
    service, history = build(jev)
    suite = TestSuiteService(service, history, settings.test_cases_path)
    response = suite.run(["TC002", "TC003", "TC023"], run_id="r1")
    assert [r.test_case_id for r in response.results] == ["TC002", "TC003", "TC023"]
    assert response.metrics.scored == 2 and response.metrics.multi_field_total == 1
    assert suite.get_run("r1").metrics.total_tests == 3
    assert suite.latest_run().metrics.run_id == "r1"


def test_suite_stops_on_missing_credentials(build, settings):
    service, history = build(FakeJEVClient(error=JEVNotConfiguredError("JEV is not configured.")))
    with pytest.raises(JEVNotConfiguredError):
        TestSuiteService(service, history, settings.test_cases_path).run()


def test_suite_continues_after_transient_error(build, settings):
    service, history = build(FakeJEVClient(error=JEVTimeoutError("slow")))
    response = TestSuiteService(service, history, settings.test_cases_path).run(["TC001", "TC002"])
    assert [r.status for r in response.results] == ["error", "error"]
    assert response.metrics.errors == 2 and response.metrics.accuracy is None


def test_unconfigured_jev_is_not_recorded_as_an_attempt(build):
    service, history = build(FakeJEVClient(error=JEVNotConfiguredError("JEV is not configured.")))
    with pytest.raises(JEVNotConfiguredError):
        service.evaluate("Find female students.")
    assert history.list_recent().total == 0
