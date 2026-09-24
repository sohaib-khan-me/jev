"""Test-suite endpoints. (Not pytest tests: those live in backend/tests/.)"""

from fastapi import APIRouter, Body, Depends

from app.dependencies import Container, get_container
from app.models.schemas import TestCase, TestRunRequest, TestRunResponse

router = APIRouter(prefix="/tests", tags=["test suite"])


@router.get("", response_model=list[TestCase], summary="List POC test cases")
def list_test_cases(container: Container = Depends(get_container)) -> list[TestCase]:
    return container.suite.list_cases()


@router.post("/run", response_model=TestRunResponse, summary="Run test cases sequentially against JEV")
def run_tests(
    body: TestRunRequest = Body(default_factory=TestRunRequest),
    container: Container = Depends(get_container),
) -> TestRunResponse:
    return container.suite.run(body.test_ids, body.run_id)


@router.get("/runs/latest", response_model=TestRunResponse | None, summary="Most recent test run, or null")
def latest_run(container: Container = Depends(get_container)) -> TestRunResponse | None:
    return container.suite.latest_run()


@router.get("/runs/{run_id}", response_model=TestRunResponse, summary="Results and metrics for one run")
def get_run(run_id: str, container: Container = Depends(get_container)) -> TestRunResponse:
    return container.suite.get_run(run_id)
