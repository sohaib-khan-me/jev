"""Loads the POC test cases, runs them sequentially, and computes metrics.

"POC field-selection accuracy" = correct / scored, over single-field cases only.
Multi-field cases are run and reported, but excluded from that number.
"""

import json
import logging
import statistics
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from app.models.schemas import CategoryMetrics, EvaluationResult, TestCase, TestRunMetrics, TestRunResponse
from app.services.evaluation_service import EvaluationService
from app.services.history_service import HistoryService
from app.utils.errors import AppError, JEVAuthError, JEVNotConfiguredError, NotFoundError, TestCasesError

logger = logging.getLogger("jev_eval.suite")

# Errors that would fail every remaining test identically: stop the run instead.
_FATAL_ERRORS = (JEVNotConfiguredError, JEVAuthError)


def load_test_cases(path: Path) -> list[TestCase]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cases = TypeAdapter(list[TestCase]).validate_python(data["test_cases"] if isinstance(data, dict) else data)
    except FileNotFoundError as exc:
        raise TestCasesError(f"Test case file not found: {path}") from exc
    except (json.JSONDecodeError, KeyError, ValidationError) as exc:
        raise TestCasesError(f"Test case file is invalid: {exc}") from exc
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise TestCasesError("Test case IDs must be unique.")
    return cases


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def compute_metrics(run_id: str, results: list[EvaluationResult]) -> TestRunMetrics:
    single = [r for r in results if r.category != "multi_field"]
    multi = [r for r in results if r.category == "multi_field"]
    answered = [r for r in results if r.status == "ok"]

    scored = [r for r in single if r.status == "ok" and r.correct is not None]
    correct = sum(1 for r in scored if r.correct)
    confidences = [r.confidence for r in answered if r.confidence is not None]
    latencies = [r.latency_ms for r in answered if r.latency_ms is not None]
    in_candidates = [r.expected_in_candidates for r in results if r.expected_in_candidates is not None]

    by_category: dict[str, list[EvaluationResult]] = defaultdict(list)
    for r in single:
        by_category[r.category or "uncategorized"].append(r)
    category_metrics = {}
    for category, items in by_category.items():
        cat_scored = [r for r in items if r.status == "ok" and r.correct is not None]
        cat_correct = sum(1 for r in cat_scored if r.correct)
        category_metrics[category] = CategoryMetrics(
            total=len(items),
            correct=cat_correct,
            incorrect=len(cat_scored) - cat_correct,
            errors=sum(1 for r in items if r.status == "error"),
            accuracy=_ratio(cat_correct, len(cat_scored)),
        )

    sources = {r.source for r in results if r.source}
    return TestRunMetrics(
        run_id=run_id,
        source=sources.pop() if len(sources) == 1 else ("mixed" if sources else None),
        total_tests=len(results),
        scored=len(scored),
        correct=correct,
        incorrect=len(scored) - correct,
        errors=sum(1 for r in single if r.status == "error"),
        accuracy=_ratio(correct, len(scored)),
        matched_alternative=sum(1 for r in scored if r.matched_alternative),
        expected_in_candidates_rate=_ratio(sum(in_candidates), len(in_candidates)),
        average_confidence=round(statistics.fmean(confidences), 4) if confidences else None,
        low_confidence_count=sum(1 for r in answered if r.low_confidence),
        average_latency_ms=round(statistics.fmean(latencies), 1) if latencies else None,
        min_latency_ms=min(latencies) if latencies else None,
        max_latency_ms=max(latencies) if latencies else None,
        by_category=dict(sorted(category_metrics.items())),
        multi_field_total=len(multi),
        multi_field_selected_in_expected_set=sum(1 for r in multi if r.selected_in_expected_set),
    )


class TestSuiteService:
    __test__ = False  # not a pytest test class

    def __init__(self, evaluation: EvaluationService, history: HistoryService, test_cases_path: Path) -> None:
        self._evaluation = evaluation
        self._history = history
        self._path = test_cases_path

    def list_cases(self) -> list[TestCase]:
        return load_test_cases(self._path)

    def run(self, test_ids: list[str] | None = None, run_id: str | None = None) -> TestRunResponse:
        cases = self.list_cases()
        if test_ids:
            unknown = set(test_ids) - {c.id for c in cases}
            if unknown:
                raise NotFoundError(f"Unknown test case IDs: {', '.join(sorted(unknown))}")
            cases = [c for c in cases if c.id in set(test_ids)]

        run_id = run_id or uuid.uuid4().hex
        results: list[EvaluationResult] = []
        for case in cases:  # sequential on purpose: easy to follow, gentle on the API
            try:
                result = self._evaluation.evaluate(
                    case.campaign, case.expected_field, test_case=case, run_id=run_id
                )
            except _FATAL_ERRORS:
                raise
            except AppError as exc:
                logger.warning("test_case_failed", extra={"test_case_id": case.id, "error_code": exc.code})
                # JEV errors are already in history; anything else (e.g. an expected
                # field missing from the schema) is recorded here so the run stays complete.
                result = next((r for r in reversed(self._history.get_run(run_id)) if r.test_case_id == case.id), None)
                if result is None:
                    result = EvaluationResult(
                        id=uuid.uuid4().hex,
                        created_at=datetime.now(timezone.utc),
                        status="error",
                        error={"code": exc.code, "message": exc.message},
                        campaign=case.campaign,
                        expected_field=case.expected_field,
                        expected_fields=case.expected_fields,
                        acceptable_alternatives=case.ambiguous_with,
                        test_case_id=case.id,
                        category=case.category,
                        run_id=run_id,
                    )
                    self._history.save(result)
            results.append(result)

        return TestRunResponse(metrics=compute_metrics(run_id, results), results=results)

    def get_run(self, run_id: str) -> TestRunResponse:
        results = self._history.get_run(run_id)
        if not results:
            raise NotFoundError(f"No test run with ID '{run_id}'.")
        return TestRunResponse(metrics=compute_metrics(run_id, results), results=results)

    def latest_run(self) -> TestRunResponse | None:
        run_id = self._history.latest_run_id()
        return self.get_run(run_id) if run_id else None
