from fastapi import APIRouter, Depends

from app.dependencies import Container, get_container
from app.models.schemas import DatabaseSchema

router = APIRouter(prefix="/schema", tags=["schema"])


@router.get("", response_model=DatabaseSchema, summary="Discovered MySQL schema (cached)")
def get_schema(container: Container = Depends(get_container)) -> DatabaseSchema:
    return container.schema_service.get_snapshot().schema


@router.post("/refresh", response_model=DatabaseSchema, summary="Re-read the schema from information_schema")
def refresh_schema(container: Container = Depends(get_container)) -> DatabaseSchema:
    return container.schema_service.refresh().schema
