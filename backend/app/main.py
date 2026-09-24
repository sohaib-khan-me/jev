"""FastAPI entry point: `uvicorn app.main:app --reload --port 8000`."""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.dependencies import Container, build_container
from app.routes import evaluation, health, schema, tests
from app.utils.errors import register_error_handlers
from app.utils.logging import configure_logging, get_request_id, new_request_id, reset_request_id, set_request_id

logger = logging.getLogger("jev_eval.http")


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or (container.settings if container else get_settings())
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "container", None) is None:
            app.state.container = build_container(settings)
        logger.info(
            "startup",
            extra={
                "database": settings.mysql_database,
                "jev_provider": settings.jev_provider,
                "jev_configured": settings.jev_configured,
                "jev_mock_mode": settings.jev_mock_mode,
                "frontend_url": settings.frontend_url,
            },
        )
        yield

    app = FastAPI(
        title="JEV Audience Field Evaluator",
        description="POC: can JEV pick the database field a natural-language campaign targets?",
        version="1.0.0",
        lifespan=lifespan,
    )
    if container is not None:  # injected (tests); otherwise built at startup
        app.state.container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        token = set_request_id(new_request_id())
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = get_request_id() or ""
            logger.info(
                "http_request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            return response
        finally:
            reset_request_id(token)

    register_error_handlers(app, debug_errors=settings.debug_errors)
    for router in (health.router, schema.router, evaluation.router, tests.router):
        app.include_router(router, prefix="/api")
    return app


app = create_app()
