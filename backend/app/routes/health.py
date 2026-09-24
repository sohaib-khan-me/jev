from fastapi import APIRouter, Depends

from app.dependencies import Container, get_container
from app.models.schemas import HealthResponse
from app.utils.errors import AppError

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service, MySQL and JEV status (no secrets)")
def health(container: Container = Depends(get_container)) -> HealthResponse:
    settings = container.settings
    mysql_error = None
    try:
        container.schema_service.check_connection()
    except AppError as exc:
        mysql_error = exc.message
    return HealthResponse(
        status="ok" if mysql_error is None else "degraded",
        mysql="connected" if mysql_error is None else "unavailable",
        mysql_error=mysql_error,
        database=settings.mysql_database,
        jev_configured=settings.jev_configured,
        jev_mock_mode=settings.jev_mock_mode,
        jev_provider=settings.jev_provider,
        jev_model=settings.jev_request_model,
    )
