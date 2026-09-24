from fastapi import APIRouter, Depends, Query

from app.dependencies import Container, get_container
from app.models.schemas import EvaluateRequest, EvaluationList, EvaluationResult
from app.utils.errors import NotFoundError

router = APIRouter(tags=["evaluation"])


@router.post("/evaluate", response_model=EvaluationResult, summary="Ask JEV which field a campaign targets")
def evaluate(body: EvaluateRequest, container: Container = Depends(get_container)) -> EvaluationResult:
    return container.evaluation.evaluate(body.campaign, body.expected_field)


@router.get("/evaluations", response_model=EvaluationList, summary="Evaluation history, newest first")
def list_evaluations(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    container: Container = Depends(get_container),
) -> EvaluationList:
    return container.history.list_recent(limit=limit, offset=offset)


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationResult, summary="One evaluation with raw JEV response")
def get_evaluation(evaluation_id: str, container: Container = Depends(get_container)) -> EvaluationResult:
    result = container.evaluation.get(evaluation_id)
    if result is None:
        raise NotFoundError(f"Evaluation '{evaluation_id}' not found.")
    return result
