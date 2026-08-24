"""Desktop-local durable Research Run command control plane.

This mirrors the operator-owned hosted command contract's claim, lease,
checkpoint, and bounded-failure semantics without any hosted call, under its
own distinct local contract versions (`research_run_local_command_receipt.v1`,
`research_run_local_command_progress.v1`). It is NOT wire-compatible with the
hosted `research_run_command_receipt.v2` receipt or the dashboard's
`research_run_command_progress.v1` contract: the local receipt is keyed
`command_state` (not `state`) and always carries `research_run_id`/
`started_at`, and local progress may retain checkpoints/attempt fields while
`command_state` is `blocked`, which the dashboard parser rejects. It exists so
one already accepted capture-bound command can be executed and audited
locally while the hosted runtime migrations remain unapplied. Any dashboard
consumption of this local state needs a separate, explicitly local-aware
projection, not a direct decode against the hosted/dashboard contracts.

Nothing here stores secrets, provider payloads, archive paths, or evidence
content. Lease tokens stay inside claims and never reach a receipt or progress
projection.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Iterator, Mapping

from investment_research_os.ids import stable_id
from investment_research_os.research_runs import (
    PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
    PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    QUESTION_TYPE_VERSION,
    WORKFLOW_CONFIG_VERSION,
)

from .storage import STAGES, SUPPORTED_WORKFLOW_IDENTITIES
from .worker import CommitteeCommandClaim


COMMAND_CONTRACT_VERSION = "research_run_local_command_receipt.v1"
PROGRESS_CONTRACT_VERSION = "research_run_local_command_progress.v1"
COMMAND_RECORD_TYPE = "research-run-command-v2"
MAXIMUM_ATTEMPTS = 2
LEASE_SECONDS = 300
LEASE_CAP_SECONDS = 3_600

_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_WORKER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CONTROLLED_CHANGE_PATTERNS = (
    re.compile(r"\b(?:add|remove|skip|disable|replace)\b.{0,40}\bgraders?\b", re.I),
    re.compile(
        r"\b(?:override|bypass|weaken|change|ignore)\b.{0,40}"
        r"\b(?:readiness|gate|eligibility|rubric|schema|workflow|disposition|"
        r"evidence requirements?)\b",
        re.I,
    ),
)
_QUESTION_TYPE_VERSIONS = frozenset(
    {QUESTION_TYPE_VERSION, PERSONAL_RESEARCH_QUESTION_TYPE_VERSION}
)
_WORKFLOW_CONFIG_VERSIONS = frozenset(
    {WORKFLOW_CONFIG_VERSION, PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION}
)


class LocalCommandStoreError(ValueError):
    """Raised when durable local command state violates its contract."""


def _record_content_hash(record: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key != "content_sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validate_command_record_shape(record: Mapping[str, Any]) -> None:
    attempts = record.get("attempts")
    checkpoints = record.get("checkpoints")
    if not isinstance(attempts, list) or not all(
        isinstance(attempt, dict) for attempt in attempts
    ):
        raise LocalCommandStoreError("local command record is invalid")
    if not isinstance(checkpoints, list) or not all(
        isinstance(checkpoint, dict) and isinstance(checkpoint.get("stage"), str)
        for checkpoint in checkpoints
    ):
        raise LocalCommandStoreError("local command record is invalid")


@dataclass(frozen=True, slots=True)
class LocalResearchRunCommand:
    """Sanitized owner-scoped command receipt. Never carries a lease token."""

    contract_version: str
    command_id: str
    operator_id: str
    security_id: str
    question_type_version: str
    workflow_config_version: str
    as_of_cutoff: datetime
    operator_focus_normalized: str | None
    capture_id: str
    capture_revision: int
    capture_content_hash: str
    idempotency_key: str
    command_state: str
    blocking_reason_codes: tuple[str, ...]
    error_code: str | None
    research_run_id: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    def as_dict(self) -> dict[str, object]:
        return {
            key: (value.isoformat() if isinstance(value, datetime) else value)
            for key, value in (
                ("blocking_reason_codes", list(self.blocking_reason_codes)),
                *(
                    (key, value)
                    for key, value in asdict(self).items()
                    if key != "blocking_reason_codes"
                ),
            )
        }


def _canonical_uuid(value: object, label: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as error:
        raise LocalCommandStoreError(f"{label} must be a UUID") from error


def _aware(value: object, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise LocalCommandStoreError(f"{label} must be timezone aware")
    return value.astimezone(UTC)


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise LocalCommandStoreError(f"{label} is invalid")
    try:
        return _aware(datetime.fromisoformat(value), label)
    except ValueError as error:
        raise LocalCommandStoreError(f"{label} is invalid") from error


def _optional_timestamp(value: object, label: str) -> datetime | None:
    return None if value is None else _timestamp(value, label)


def _wire(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _normalized_focus(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LocalCommandStoreError("operator focus must be text")
    if len(value) > 2_000:
        raise LocalCommandStoreError("operator focus exceeds 2000 characters")
    normalized = re.sub(r"\s+", " ", value).strip()
    if any(pattern.search(normalized) for pattern in _CONTROLLED_CHANGE_PATTERNS):
        raise LocalCommandStoreError("operator focus cannot alter workflow behavior")
    return normalized or None


def _idempotency_key(
    *,
    operator_id: str,
    security_id: str,
    question_type_version: str,
    workflow_config_version: str,
    as_of_cutoff: datetime,
    operator_focus_normalized: str | None,
    capture_id: str,
    capture_revision: int,
    capture_content_hash: str,
) -> str:
    identity = "\n".join(
        (
            operator_id,
            security_id,
            question_type_version,
            workflow_config_version,
            as_of_cutoff.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            operator_focus_normalized or "<null>",
            capture_id,
            str(capture_revision),
            capture_content_hash,
        )
    )
    return hashlib.sha256(identity.encode()).hexdigest()


class FileResearchRunCommandStore:
    """Restart-safe single-operator local store for Research Run commands."""

    def __init__(
        self,
        root: Path,
        *,
        operator_id: str,
        clock: Callable[[], datetime],
    ) -> None:
        root = Path(root)
        if root.is_symlink():
            raise LocalCommandStoreError("command storage root must not be a symlink")
        self._operator_id = _canonical_uuid(operator_id, "operator identity")
        self._clock = clock
        self._root = root
        self._operator_root = root / self._operator_id
        if self._operator_root.is_symlink():
            raise LocalCommandStoreError(
                "command operator directory must not be a symlink"
            )
        self._operator_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        os.chmod(self._operator_root, 0o700)
        self._lock_path = root / ".lock"

    # ------------------------------------------------------------------ enqueue

    def enqueue(
        self,
        *,
        security_id: str,
        as_of_cutoff: datetime,
        operator_focus: str | None,
        question_type_version: str,
        workflow_config_version: str,
        capture_id: str,
        capture_revision: int,
        capture_content_hash: str,
    ) -> LocalResearchRunCommand:
        if (question_type_version, workflow_config_version) not in (
            SUPPORTED_WORKFLOW_IDENTITIES
        ):
            raise LocalCommandStoreError("unsupported research workflow identity")
        if (
            type(capture_revision) is not int
            or capture_revision < 1
            or not isinstance(capture_content_hash, str)
            or _SHA256_PATTERN.fullmatch(capture_content_hash) is None
        ):
            raise LocalCommandStoreError("capture identity is invalid")
        canonical_security_id = _canonical_uuid(security_id, "security identity")
        canonical_capture_id = _canonical_uuid(capture_id, "capture identity")
        cutoff = _aware(as_of_cutoff, "as-of cutoff")
        focus = _normalized_focus(operator_focus)
        now = self._now()
        if cutoff > now:
            raise LocalCommandStoreError("as-of cutoff is invalid")
        idempotency_key = _idempotency_key(
            operator_id=self._operator_id,
            security_id=canonical_security_id,
            question_type_version=question_type_version,
            workflow_config_version=workflow_config_version,
            as_of_cutoff=cutoff,
            operator_focus_normalized=focus,
            capture_id=canonical_capture_id,
            capture_revision=capture_revision,
            capture_content_hash=capture_content_hash,
        )
        command_id = stable_id(
            self._operator_id,
            COMMAND_RECORD_TYPE,
            idempotency_key,
        )
        with self._locked():
            existing = self._read(command_id)
            if existing is not None:
                if existing["idempotency_key"] != idempotency_key:
                    raise LocalCommandStoreError(
                        "research run command identity collision"
                    )
                return self._receipt(existing)
            record: dict[str, Any] = {
                "contract_version": COMMAND_CONTRACT_VERSION,
                "command_id": command_id,
                "operator_id": self._operator_id,
                "security_id": canonical_security_id,
                "question_type_version": question_type_version,
                "workflow_config_version": workflow_config_version,
                "as_of_cutoff": cutoff.isoformat(),
                "operator_focus_normalized": focus,
                "capture_id": canonical_capture_id,
                "capture_revision": capture_revision,
                "capture_content_hash": capture_content_hash,
                "idempotency_key": idempotency_key,
                "command_state": "queued",
                "blocking_reason_codes": [],
                "error_code": None,
                "research_run_id": None,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "started_at": None,
                "finished_at": None,
                "attempts": [],
                "checkpoints": [],
            }
            self._write(record)
            return self._receipt(record)

    # ------------------------------------------------------------------- reads

    def get(self, command_id: str) -> LocalResearchRunCommand | None:
        record = self._read(_canonical_uuid(command_id, "command identity"))
        return None if record is None else self._receipt(record)

    def progress(self, command_id: str) -> dict[str, object] | None:
        record = self._read(_canonical_uuid(command_id, "command identity"))
        if record is None:
            return None
        attempt = self._latest_attempt(record)
        completed = [checkpoint["stage"] for checkpoint in record["checkpoints"]]
        if attempt is None:
            return {
                "contract_version": PROGRESS_CONTRACT_VERSION,
                "operator_id": record["operator_id"],
                "command_id": record["command_id"],
                "command_state": record["command_state"],
                "attempt_id": None,
                "attempt_number": None,
                "attempt_state": None,
                "active_stage": None,
                "completed_stages": completed,
                "lease_started_at": None,
                "lease_expires_at": None,
                "failure_stage": None,
                "error_code": None,
                "retryable": None,
                "updated_at": record["updated_at"],
            }
        return {
            "contract_version": PROGRESS_CONTRACT_VERSION,
            "operator_id": record["operator_id"],
            "command_id": record["command_id"],
            "command_state": record["command_state"],
            "attempt_id": attempt["attempt_id"],
            "attempt_number": attempt["attempt_number"],
            "attempt_state": attempt["attempt_state"],
            "active_stage": attempt["active_stage"],
            "completed_stages": completed,
            "lease_started_at": attempt["lease_started_at"],
            "lease_expires_at": attempt["lease_expires_at"],
            "failure_stage": attempt["failure_stage"],
            "error_code": attempt["error_code"],
            "retryable": attempt["retryable"],
            "updated_at": record["updated_at"],
        }

    # ------------------------------------------------------- command store port

    def claim_next(self, worker_id: str) -> CommitteeCommandClaim | None:
        if (
            not isinstance(worker_id, str)
            or worker_id != worker_id.strip()
            or _WORKER_ID_PATTERN.fullmatch(worker_id) is None
        ):
            raise LocalCommandStoreError("invalid committee worker identity")
        with self._locked():
            now = self._now()
            self._recover_expired_leases(now)
            resumed = self._resume_own_attempt(worker_id, now)
            if resumed is not None:
                return resumed
            return self._start_new_attempt(worker_id, now)

    def renew_lease(self, claim: CommitteeCommandClaim) -> None:
        with self._locked():
            now = self._now()
            record, attempt = self._live_attempt(claim, claim.next_stage, now)
            attempt["lease_expires_at"] = self._extended_lease(attempt, now)
            self._touch(record, now)
            self._write(record)

    def checkpoint(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        artifact_id: str,
    ) -> None:
        if stage not in STAGES:
            raise LocalCommandStoreError("committee checkpoint stage is invalid")
        canonical_artifact_id = _canonical_uuid(artifact_id, "artifact identity")
        with self._locked():
            now = self._now()
            record = self._require(claim.command_id)
            existing = self._checkpoint_for(record, stage)
            if existing is not None:
                if (
                    existing["attempt_id"] != claim.attempt_id
                    or existing["artifact_id"] != canonical_artifact_id
                    or not any(
                        attempt["attempt_id"] == existing["attempt_id"]
                        and attempt["lease_token"] == claim.lease_token
                        for attempt in record["attempts"]
                    )
                ):
                    if stage == "research_run":
                        raise LocalCommandStoreError(
                            "conflicting research run checkpoint"
                        )
                    raise LocalCommandStoreError("conflicting command checkpoint")
                return
            record, attempt = self._live_attempt(claim, stage, now)
            expected_ordinal = STAGES.index(stage) + 1
            if len(record["checkpoints"]) + 1 != expected_ordinal:
                raise LocalCommandStoreError(
                    "research run command checkpoints are invalid"
                )
            record["checkpoints"].append(
                {
                    "stage": stage,
                    "stage_ordinal": expected_ordinal,
                    "artifact_id": canonical_artifact_id,
                    "attempt_id": attempt["attempt_id"],
                    "checkpointed_at": now.isoformat(),
                }
            )
            if expected_ordinal == len(STAGES):
                attempt["attempt_state"] = "completed"
                attempt["active_stage"] = None
                attempt["active_stage_claimed_at"] = None
                attempt["finished_at"] = now.isoformat()
                record["command_state"] = "completed"
                record["blocking_reason_codes"] = []
                record["error_code"] = None
                record["research_run_id"] = self._research_run_id(record)
                record["finished_at"] = now.isoformat()
            else:
                attempt["active_stage"] = None
                attempt["active_stage_claimed_at"] = None
                attempt["lease_expires_at"] = self._extended_lease(attempt, now)
            self._touch(record, now)
            self._write(record)

    def fail(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        error_code: str,
        retryable: bool,
    ) -> None:
        if (
            stage not in STAGES
            or not isinstance(error_code, str)
            or _ERROR_CODE_PATTERN.fullmatch(error_code) is None
            or type(retryable) is not bool
        ):
            raise LocalCommandStoreError(
                "committee command failure classification is invalid"
            )
        with self._locked():
            now = self._now()
            record = self._require(claim.command_id)
            attempt = self._attempt_for(record, claim.attempt_id)
            if attempt["attempt_state"] == "failed":
                if (
                    attempt["lease_token"] != claim.lease_token
                    or attempt["failure_stage"] != stage
                    or attempt["error_code"] != error_code
                    or attempt["retryable"] is not retryable
                ):
                    raise LocalCommandStoreError(
                        "conflicting research run command failure"
                    )
                return
            record, attempt = self._live_attempt(claim, stage, now)
            self._terminalize_attempt(
                record,
                attempt,
                stage=stage,
                error_code=error_code,
                retryable=retryable,
                now=now,
            )
            self._write(record)

    def block(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        blocking_reason_codes: tuple[str, ...],
    ) -> None:
        """Record an honest deterministic stop before a stage runs.

        A blocked command keeps every checkpoint it genuinely earned and never
        reports completion. Its attempt terminalizes with the first blocking
        reason so the audit trail names the exact boundary.
        """
        reasons = tuple(blocking_reason_codes)
        if (
            stage not in STAGES
            or not reasons
            or any(
                not isinstance(reason, str)
                or _ERROR_CODE_PATTERN.fullmatch(reason) is None
                for reason in reasons
            )
        ):
            raise LocalCommandStoreError("command blocking classification is invalid")
        with self._locked():
            now = self._now()
            record, attempt = self._live_attempt(claim, stage, now)
            attempt["attempt_state"] = "failed"
            attempt["active_stage"] = None
            attempt["active_stage_claimed_at"] = None
            attempt["failure_stage"] = stage
            attempt["error_code"] = reasons[0]
            attempt["retryable"] = False
            attempt["finished_at"] = now.isoformat()
            record["command_state"] = "blocked"
            record["blocking_reason_codes"] = list(reasons)
            record["error_code"] = None
            record["research_run_id"] = self._research_run_id(record)
            record["finished_at"] = now.isoformat()
            self._touch(record, now)
            self._write(record)

    # ---------------------------------------------------------------- internals

    def _now(self) -> datetime:
        return _aware(self._clock(), "command clock")

    def _touch(self, record: dict[str, Any], now: datetime) -> None:
        record["updated_at"] = now.isoformat()

    def _command_path(self, command_id: str) -> Path:
        return self._operator_root / f"{command_id}.json"

    def _read(self, command_id: str) -> dict[str, Any] | None:
        path = self._command_path(command_id)
        if self._operator_root.is_symlink() or path.is_symlink() or not path.is_file():
            return None
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise LocalCommandStoreError("local command record is unreadable") from error
        if (
            not isinstance(record, dict)
            or record.get("contract_version") != COMMAND_CONTRACT_VERSION
            or record.get("command_id") != command_id
            or record.get("operator_id") != self._operator_id
        ):
            raise LocalCommandStoreError("local command record is invalid")
        content_sha256 = record.pop("content_sha256", None)
        if content_sha256 != _record_content_hash(record):
            raise LocalCommandStoreError("local command record is invalid")
        _validate_command_record_shape(record)
        return record

    def _require(self, command_id: str) -> dict[str, Any]:
        record = self._read(_canonical_uuid(command_id, "command identity"))
        if record is None:
            raise LocalCommandStoreError("research run command is unavailable")
        return record

    def _write(self, record: Mapping[str, Any]) -> None:
        path = self._command_path(str(record["command_id"]))
        stamped = dict(record)
        stamped["content_sha256"] = _record_content_hash(stamped)
        body = json.dumps(stamped, sort_keys=True, separators=(",", ":")).encode()
        with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(body)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.chmod(temporary_path, 0o600)
        temporary_path.replace(path)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        descriptor = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self._operator_root.glob("*.json")):
            if path.is_symlink():
                continue
            record = self._read(path.stem)
            if record is not None:
                records.append(record)
        records.sort(key=lambda record: (record["created_at"], record["command_id"]))
        return records

    def _receipt(self, record: Mapping[str, Any]) -> LocalResearchRunCommand:
        return LocalResearchRunCommand(
            contract_version=COMMAND_CONTRACT_VERSION,
            command_id=str(record["command_id"]),
            operator_id=str(record["operator_id"]),
            security_id=str(record["security_id"]),
            question_type_version=str(record["question_type_version"]),
            workflow_config_version=str(record["workflow_config_version"]),
            as_of_cutoff=_timestamp(record["as_of_cutoff"], "as-of cutoff"),
            operator_focus_normalized=(
                None
                if record["operator_focus_normalized"] is None
                else str(record["operator_focus_normalized"])
            ),
            capture_id=str(record["capture_id"]),
            capture_revision=int(record["capture_revision"]),
            capture_content_hash=str(record["capture_content_hash"]),
            idempotency_key=str(record["idempotency_key"]),
            command_state=str(record["command_state"]),
            blocking_reason_codes=tuple(record["blocking_reason_codes"]),
            error_code=(
                None if record["error_code"] is None else str(record["error_code"])
            ),
            research_run_id=(
                None
                if record["research_run_id"] is None
                else str(record["research_run_id"])
            ),
            created_at=_timestamp(record["created_at"], "created at"),
            updated_at=_timestamp(record["updated_at"], "updated at"),
            started_at=_optional_timestamp(record["started_at"], "started at"),
            finished_at=_optional_timestamp(record["finished_at"], "finished at"),
        )

    def _completed_stages(self, record: Mapping[str, Any]) -> tuple[str, ...]:
        completed = tuple(
            str(checkpoint["stage"]) for checkpoint in record["checkpoints"]
        )
        if completed != STAGES[: len(completed)]:
            raise LocalCommandStoreError(
                "research run command checkpoints are invalid"
            )
        return completed

    def _checkpoint_for(
        self,
        record: Mapping[str, Any],
        stage: str,
    ) -> dict[str, Any] | None:
        for checkpoint in record["checkpoints"]:
            if checkpoint["stage"] == stage:
                return checkpoint
        return None

    def _research_run_id(self, record: Mapping[str, Any]) -> str | None:
        checkpoint = self._checkpoint_for(record, "research_run")
        return None if checkpoint is None else str(checkpoint["artifact_id"])

    def _latest_attempt(self, record: Mapping[str, Any]) -> dict[str, Any] | None:
        attempts = record["attempts"]
        if not attempts:
            return None
        return max(attempts, key=lambda attempt: attempt["attempt_number"])

    def _attempt_for(
        self,
        record: Mapping[str, Any],
        attempt_id: str,
    ) -> dict[str, Any]:
        for attempt in record["attempts"]:
            if attempt["attempt_id"] == attempt_id:
                return attempt
        raise LocalCommandStoreError("research run command attempt is unavailable")

    def _extended_lease(self, attempt: Mapping[str, Any], now: datetime) -> str:
        started = _timestamp(attempt["lease_started_at"], "lease start")
        expires = _timestamp(attempt["lease_expires_at"], "lease expiry")
        extended = min(
            started + timedelta(seconds=LEASE_CAP_SECONDS),
            max(expires, now + timedelta(seconds=LEASE_SECONDS)),
        )
        return extended.isoformat()

    def _live_attempt(
        self,
        claim: CommitteeCommandClaim,
        stage: str,
        now: datetime,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        record = self._require(claim.command_id)
        attempt = self._attempt_for(record, claim.attempt_id)
        if (
            record["command_state"] != "running"
            or attempt["attempt_state"] != "running"
            or attempt["active_stage"] != stage
            or attempt["lease_token"] != claim.lease_token
            or _timestamp(attempt["lease_expires_at"], "lease expiry") <= now
        ):
            raise LocalCommandStoreError("research run command lease is invalid")
        return record, attempt

    def _terminalize_attempt(
        self,
        record: dict[str, Any],
        attempt: dict[str, Any],
        *,
        stage: str,
        error_code: str,
        retryable: bool,
        now: datetime,
    ) -> None:
        attempt["attempt_state"] = "failed"
        attempt["active_stage"] = None
        attempt["active_stage_claimed_at"] = None
        attempt["failure_stage"] = stage
        attempt["error_code"] = error_code
        attempt["retryable"] = retryable
        attempt["finished_at"] = now.isoformat()
        if retryable and int(attempt["attempt_number"]) < MAXIMUM_ATTEMPTS:
            record["command_state"] = "queued"
            record["blocking_reason_codes"] = []
            record["error_code"] = None
            record["research_run_id"] = None
            record["started_at"] = None
            record["finished_at"] = None
        else:
            record["command_state"] = "failed"
            record["blocking_reason_codes"] = []
            record["error_code"] = error_code
            record["research_run_id"] = self._research_run_id(record)
            record["finished_at"] = now.isoformat()
        self._touch(record, now)

    def _recover_expired_leases(self, now: datetime) -> None:
        for record in self._records():
            if record["command_state"] != "running":
                continue
            for attempt in record["attempts"]:
                if attempt["attempt_state"] != "running" or (
                    _timestamp(attempt["lease_expires_at"], "lease expiry") > now
                ):
                    continue
                completed = self._completed_stages(record)
                self._terminalize_attempt(
                    record,
                    attempt,
                    stage=STAGES[len(completed)],
                    error_code="worker_lease_expired",
                    retryable=True,
                    now=now,
                )
                self._write(record)
                break

    def _claim(
        self,
        record: Mapping[str, Any],
        attempt: Mapping[str, Any],
        *,
        next_stage: str,
        completed: tuple[str, ...],
    ) -> CommitteeCommandClaim:
        return CommitteeCommandClaim(
            command_id=str(record["command_id"]),
            operator_id=str(record["operator_id"]),
            security_id=str(record["security_id"]),
            capture_id=str(record["capture_id"]),
            capture_revision=int(record["capture_revision"]),
            capture_content_hash=str(record["capture_content_hash"]),
            question_type_version=str(record["question_type_version"]),
            workflow_config_version=str(record["workflow_config_version"]),
            as_of_cutoff=_timestamp(record["as_of_cutoff"], "as-of cutoff"),
            operator_focus=(
                None
                if record["operator_focus_normalized"] is None
                else str(record["operator_focus_normalized"])
            ),
            attempt_id=str(attempt["attempt_id"]),
            attempt_number=int(attempt["attempt_number"]),
            lease_token=str(attempt["lease_token"]),
            next_stage=next_stage,
            completed_stages=completed,
            research_run_id=self._research_run_id(record),
        )

    def _resume_own_attempt(
        self,
        worker_id: str,
        now: datetime,
    ) -> CommitteeCommandClaim | None:
        for record in self._records():
            if record["command_state"] != "running":
                continue
            for attempt in record["attempts"]:
                if (
                    attempt["worker_id"] != worker_id
                    or attempt["attempt_state"] != "running"
                    or attempt["active_stage"] is not None
                    or _timestamp(attempt["lease_expires_at"], "lease expiry") <= now
                ):
                    continue
                completed = self._completed_stages(record)
                if len(completed) >= len(STAGES):
                    raise LocalCommandStoreError(
                        "research run command checkpoints are invalid"
                    )
                next_stage = STAGES[len(completed)]
                attempt["active_stage"] = next_stage
                attempt["active_stage_claimed_at"] = now.isoformat()
                attempt["lease_expires_at"] = self._extended_lease(attempt, now)
                self._touch(record, now)
                self._write(record)
                return self._claim(
                    record,
                    attempt,
                    next_stage=next_stage,
                    completed=completed,
                )
        return None

    def _start_new_attempt(
        self,
        worker_id: str,
        now: datetime,
    ) -> CommitteeCommandClaim | None:
        for record in self._records():
            if record["command_state"] != "queued":
                continue
            completed = self._completed_stages(record)
            if len(completed) >= len(STAGES):
                raise LocalCommandStoreError(
                    "research run command checkpoints are invalid"
                )
            attempt_number = len(record["attempts"]) + 1
            if attempt_number > MAXIMUM_ATTEMPTS:
                raise LocalCommandStoreError(
                    "research run command attempt limit exceeded"
                )
            next_stage = STAGES[len(completed)]
            attempt = {
                "attempt_id": str(uuid.uuid4()),
                "attempt_number": attempt_number,
                "worker_id": worker_id,
                "lease_token": str(uuid.uuid4()),
                "lease_started_at": now.isoformat(),
                "lease_expires_at": (
                    now + timedelta(seconds=LEASE_SECONDS)
                ).isoformat(),
                "attempt_state": "running",
                "active_stage": next_stage,
                "active_stage_claimed_at": now.isoformat(),
                "failure_stage": None,
                "error_code": None,
                "retryable": None,
                "started_at": now.isoformat(),
                "finished_at": None,
            }
            record["attempts"].append(attempt)
            record["command_state"] = "running"
            record["blocking_reason_codes"] = []
            record["error_code"] = None
            record["research_run_id"] = None
            record["started_at"] = now.isoformat()
            record["finished_at"] = None
            self._touch(record, now)
            self._write(record)
            return self._claim(
                record,
                attempt,
                next_stage=next_stage,
                completed=completed,
            )
        return None


__all__ = [
    "COMMAND_CONTRACT_VERSION",
    "FileResearchRunCommandStore",
    "LocalCommandStoreError",
    "LocalResearchRunCommand",
    "PROGRESS_CONTRACT_VERSION",
]
