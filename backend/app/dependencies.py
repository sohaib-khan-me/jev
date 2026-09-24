"""Wires services together once per app and exposes them to routes.

Services live on `app.state.container`, not in module globals, so tests can
build an app with fake services (see tests/conftest.py).
"""

from dataclasses import dataclass

from fastapi import Request

from app.config import Settings
from app.database.connection import create_mysql_engine
from app.services.candidate_service import CandidateService
from app.services.evaluation_service import EvaluationService
from app.services.history_service import HistoryService
from app.services.jev_service import JEVClient, create_jev_client
from app.services.mysql_schema_service import MySQLSchemaService
from app.services.suite_service import TestSuiteService


@dataclass
class Container:
    settings: Settings
    schema_service: MySQLSchemaService
    jev_client: JEVClient
    history: HistoryService
    evaluation: EvaluationService
    suite: TestSuiteService


def build_container(
    settings: Settings,
    *,
    schema_service: MySQLSchemaService | None = None,
    jev_client: JEVClient | None = None,
) -> Container:
    schema_service = schema_service or MySQLSchemaService(create_mysql_engine(settings), settings)
    jev_client = jev_client or create_jev_client(settings)
    history = HistoryService(settings.history_db_path)
    evaluation = EvaluationService(
        schema_service, CandidateService(settings.candidate_max_fields), jev_client, history, settings
    )
    suite = TestSuiteService(evaluation, history, settings.test_cases_path)
    return Container(settings, schema_service, jev_client, history, evaluation, suite)


def get_container(request: Request) -> Container:
    return request.app.state.container
