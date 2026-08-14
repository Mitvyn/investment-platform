from __future__ import annotations

from datetime import UTC, datetime
import re
import uuid
from typing import Any, Mapping

from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)
from investment_research_os.research_runs import (
    PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
    PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    QUESTION_TYPE_VERSION,
    WORKFLOW_CONFIG_VERSION,
)

from .worker import CommitteeCommandClaim


SUPPORTED_WORKFLOW_IDENTITIES = frozenset(
    {
        (QUESTION_TYPE_VERSION, WORKFLOW_CONFIG_VERSION),
        (
            PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
            PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
        ),
    }
)
ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
STAGES = (
    "research_run",
    "evidence_bundle",
    "valuation_snapshot",
    "grader_committee",
    "committee_memo",
    "readiness_thesis",
)


class SupabaseCommitteeCommandStore:
    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def _rpc(self, name: str, payload: Mapping[str, Any]) -> Any:
        response = self.transport.request_json(
            "POST",
            f"{self.settings.url.rstrip('/')}/rest/v1/rpc/{name}",
            headers={
                "Content-Type": "application/json",
                "apikey": self.settings.secret_key,
            },
            payload=payload,
        )
        if not 200 <= response.status < 300:
            raise EvidenceStorageError(
                f"committee command store returned HTTP {response.status} for {name}"
            )
        return response.payload

    def claim_next(self, worker_id: str) -> CommitteeCommandClaim | None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        payload = self._rpc(
            "iros_claim_research_run_command_v2",
            {"selected_worker_id": worker_id.strip()},
        )
        if not isinstance(payload, list):
            raise EvidenceStorageError("committee command claim response is invalid")
        if not payload:
            return None
        if len(payload) != 1 or not isinstance(payload[0], dict):
            raise EvidenceStorageError("committee command claim count is invalid")
        return _claim_from_row(payload[0])

    def checkpoint(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        artifact_id: str,
    ) -> None:
        if stage not in STAGES:
            raise ValueError("committee checkpoint stage is invalid")
        self._rpc(
            "iros_checkpoint_research_run_command",
            {
                "selected_command_id": _uuid_text(claim.command_id),
                "selected_attempt_id": _uuid_text(claim.attempt_id),
                "selected_lease_token": _uuid_text(claim.lease_token),
                "selected_stage": stage,
                "selected_artifact_id": _uuid_text(artifact_id),
            },
        )

    def renew_lease(self, claim: CommitteeCommandClaim) -> None:
        self._rpc(
            "iros_renew_research_run_command_lease",
            {
                "selected_command_id": _uuid_text(claim.command_id),
                "selected_attempt_id": _uuid_text(claim.attempt_id),
                "selected_lease_token": _uuid_text(claim.lease_token),
                "selected_stage": claim.next_stage,
            },
        )

    def fail(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        error_code: str,
        retryable: bool,
    ) -> None:
        if stage not in STAGES or ERROR_CODE_PATTERN.fullmatch(error_code) is None:
            raise ValueError("committee command failure classification is invalid")
        self._rpc(
            "iros_fail_research_run_command",
            {
                "selected_command_id": _uuid_text(claim.command_id),
                "selected_attempt_id": _uuid_text(claim.attempt_id),
                "selected_lease_token": _uuid_text(claim.lease_token),
                "selected_stage": stage,
                "selected_error_code": error_code,
                "selected_retryable": retryable,
            },
        )


def _claim_from_row(row: Mapping[str, Any]) -> CommitteeCommandClaim:
    expected_fields = {
        "command_id",
        "operator_id",
        "security_id",
        "capture_id",
        "capture_revision",
        "capture_content_hash",
        "question_type_version",
        "workflow_config_version",
        "as_of_cutoff",
        "operator_focus_normalized",
        "attempt_id",
        "attempt_number",
        "lease_token",
        "next_stage",
        "completed_stages",
        "research_run_id",
    }
    if set(row) != expected_fields:
        raise EvidenceStorageError("committee command claim is malformed")
    try:
        cutoff = datetime.fromisoformat(str(row["as_of_cutoff"]).replace("Z", "+00:00"))
        focus = row["operator_focus_normalized"]
        completed = row["completed_stages"]
        research_run_id = row["research_run_id"]
        claim = CommitteeCommandClaim(
            command_id=_uuid_text(row["command_id"]),
            operator_id=_uuid_text(row["operator_id"]),
            security_id=_uuid_text(row["security_id"]),
            capture_id=_uuid_text(row["capture_id"]),
            capture_revision=int(row["capture_revision"]),
            capture_content_hash=str(row["capture_content_hash"]),
            question_type_version=str(row["question_type_version"]),
            workflow_config_version=str(row["workflow_config_version"]),
            as_of_cutoff=cutoff.astimezone(UTC),
            operator_focus=None if focus is None else str(focus),
            attempt_id=_uuid_text(row["attempt_id"]),
            attempt_number=int(row["attempt_number"]),
            lease_token=_uuid_text(row["lease_token"]),
            next_stage=str(row["next_stage"]),
            completed_stages=tuple(completed),
            research_run_id=(
                None if research_run_id is None else _uuid_text(research_run_id)
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceStorageError("committee command claim is malformed") from error
    if (
        cutoff.tzinfo is None
        or cutoff.utcoffset() is None
        or (
            claim.question_type_version,
            claim.workflow_config_version,
        )
        not in SUPPORTED_WORKFLOW_IDENTITIES
        or claim.attempt_number not in (1, 2)
        or type(row["capture_revision"]) is not int
        or claim.capture_revision < 1
        or re.fullmatch(r"[0-9a-f]{64}", claim.capture_content_hash) is None
        or claim.next_stage not in STAGES
        or not isinstance(completed, list)
        or claim.completed_stages != STAGES[: STAGES.index(claim.next_stage)]
        or (claim.next_stage == "research_run" and claim.research_run_id is not None)
        or (claim.next_stage != "research_run" and claim.research_run_id is None)
        or (
            claim.operator_focus is not None
            and (
                not claim.operator_focus
                or len(claim.operator_focus) > 2_000
                or re.sub(r"\s+", " ", claim.operator_focus).strip()
                != claim.operator_focus
            )
        )
    ):
        raise EvidenceStorageError("committee command claim is malformed")
    return claim


def _uuid_text(value: object) -> str:
    return str(uuid.UUID(str(value)))


__all__ = ["SupabaseCommitteeCommandStore"]
