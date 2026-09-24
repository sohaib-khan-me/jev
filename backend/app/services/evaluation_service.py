"""Runs one campaign through the pipeline and scores the result locally.

    campaign -> schema -> candidates -> JEV choice -> compare with expected -> history

The expected field is validated against the schema up front, but it is only
*compared* after JEV has answered. It is never passed to the JEV client.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from app.config import Settings
from app.models.schemas import EvaluationResult, TestCase
from app.services.candidate_service import CandidateService, ambiguity_notes
from app.services.history_service import HistoryService
from app.services.jev_service import JEVClient
from app.services.mysql_schema_service import MySQLSchemaService
from app.utils.errors import InvalidExpectedFieldError, JEVError, JEVNotConfiguredError, NoCandidatesError

logger = logging.getLogger("jev_eval.evaluation")


class EvaluationService:
    def __init__(
        self,
        schema_service: MySQLSchemaService,
        candidate_service: CandidateService,
        jev_client: JEVClient,
        history: HistoryService,
        settings: Settings,
    ) -> None:
        self._schema = schema_service
        self._candidates = candidate_service
        self._jev = jev_client
        self._history = history
        self._settings = settings

    def evaluate(
        self,
        campaign: str,
        expected_field: str | None = None,
        *,
        test_case: TestCase | None = None,
        run_id: str | None = None,
    ) -> EvaluationResult:
        """Evaluate one campaign. JEV failures are saved to history and then re-raised."""
        snapshot = self._schema.get_snapshot()
        schema = snapshot.schema

        expected_fields = test_case.expected_fields if test_case else []
        known = set(schema.field_ids())
        for field in [f for f in [expected_field, *expected_fields] if f]:
            if field not in known:
                raise InvalidExpectedFieldError(f"Expected field '{field}' does not exist in the current schema.")

        candidates = self._candidates.generate(campaign, snapshot)
        if not candidates:
            raise NoCandidatesError("No candidate fields could be generated for this campaign.")
        candidate_ids = {c.field for c in candidates}

        result = EvaluationResult(
            id=uuid.uuid4().hex,
            created_at=datetime.now(timezone.utc),
            status="ok",
            campaign=campaign,
            expected_field=expected_field,
            expected_fields=expected_fields,
            acceptable_alternatives=test_case.ambiguous_with if test_case else [],
            candidates=candidates,
            source=self._jev.source,
            test_case_id=test_case.id if test_case else None,
            category=test_case.category if test_case else None,
            run_id=run_id,
        )
        if expected_field:
            result.expected_in_candidates = expected_field in candidate_ids
        elif expected_fields:
            result.expected_in_candidates = all(f in candidate_ids for f in expected_fields)

        try:
            # Only the campaign and schema-derived data go to JEV.
            jev = self._jev.choose(campaign, candidates, schema, dict(snapshot.column_values))
        except JEVNotConfiguredError:
            raise  # no request was made, so there is nothing to record
        except JEVError as exc:
            result.status = "error"
            result.error = {"code": exc.code, "message": exc.message}
            self._history.save(result)
            self._log(result)
            raise

        result.selected_field = jev.selected_field
        result.confidence = jev.confidence
        result.low_confidence = (
            None if jev.confidence is None else jev.confidence < self._settings.jev_low_confidence_threshold
        )
        result.probabilities = jev.probabilities
        result.probabilities_note = jev.probabilities_note
        result.latency_ms = jev.latency_ms
        result.attempts = jev.attempts
        result.model = jev.model
        result.usage = jev.usage
        result.source = jev.source
        result.raw_response = jev.raw_response

        # Local evaluation: a plain equality check, independent of confidence.
        if expected_field:
            result.correct = jev.selected_field == expected_field
            result.matched_alternative = (not result.correct) and jev.selected_field in result.acceptable_alternatives
        if expected_fields:
            result.selected_in_expected_set = jev.selected_field in expected_fields

        result.ambiguity_notes = ambiguity_notes(jev.selected_field, candidates, schema)
        if result.expected_in_candidates is False:
            result.ambiguity_notes.append("The expected field was not among the candidates sent to JEV.")

        self._history.save(result)
        self._log(result)
        return result

    def get(self, evaluation_id: str) -> EvaluationResult | None:
        return self._history.get(evaluation_id)

    def _log(self, result: EvaluationResult) -> None:
        extra = {
            "evaluation_id": result.id,
            "test_case_id": result.test_case_id,
            "run_id": result.run_id,
            "source": result.source,
            "status": result.status,
            "selected_field": result.selected_field,
            "confidence": result.confidence,
            "correct": result.correct,
            "latency_ms": result.latency_ms,
            "attempts": result.attempts,
            "candidate_count": len(result.candidates),
        }
        if self._settings.log_campaign_text:
            extra["campaign"] = result.campaign
        else:
            extra["campaign_sha256"] = hashlib.sha256(result.campaign.encode()).hexdigest()[:16]
        if result.error:
            extra["error_code"] = result.error["code"]
        logger.info("jev_evaluation", extra=extra)

