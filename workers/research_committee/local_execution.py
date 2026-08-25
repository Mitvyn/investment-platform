"""Bounded desktop-local Research Run command execution.

One already queued capture-bound command is claimed, validated against its
exact accepted capture, executed through the existing deterministic Research
workflow stages, and checkpointed through the existing repository boundaries.

A stage with no locally available implementation or activation records an
explicit blocked state at that exact boundary. Nothing here fabricates
research, valuation, memo, thesis, citation, or completion, and no provider,
model, hosted, or network client is constructed.
"""

from __future__ import annotations

import re
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Mapping
from zipfile import BadZipFile, ZipFile

from workers.primary_sources.plans import (
    PrimarySourcePlanError,
    load_primary_source_plan,
)
from workers.primary_sources.storage import (
    FilePrimarySourceCaptureRepository,
    PrimarySourceStorageError,
)

from .capture_research_run import AcceptedCaptureSecurityContext
from .composition import (
    compose_accepted_capture_research_run_stage,
    compose_dynamic_persistent_evidence_bundle_stage,
)
from .local_commands import FileResearchRunCommandStore
from .storage import STAGES
from .worker import (
    CommitteeCommandClaim,
    CommitteeLeaseLostError,
    ResearchRunStage,
    ResearchRunStageError,
    ThreadedCommitteeLeaseKeeper,
)


EMBEDDED_PLAN_ENTRY = "primary-source-plan.json"
MAXIMUM_BOUNDED_STAGES = 12

# Deterministic local preflight. Each entry names why a stage cannot run on the
# desktop-local path today. These are honest boundaries, not failures.
LOCAL_STAGE_BLOCKING_REASONS: Mapping[str, tuple[str, ...]] = {
    "evidence_bundle": ("evidence_bundle_local_persistence_unavailable",),
    "valuation_snapshot": ("approved_valuation_source_activation",),
    "grader_committee": ("approved_model_provider_activation",),
    "committee_memo": ("approved_model_provider_activation",),
    "readiness_thesis": ("approved_model_provider_activation",),
}
_DEFAULT_BLOCKING_REASONS = ("local_stage_implementation_unavailable",)

_SAFE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SAFE_DIAGNOSTIC_FIELDS = frozenset(
    {
        "attempt_number",
        "blocking_reason_codes",
        "command_id",
        "artifact_id",
        "error_code",
        "retryable",
        "stage",
    }
)
_SAFE_DIAGNOSTIC_EVENTS = frozenset(
    {
        "capture_validated",
        "command_claimed",
        "stage_blocked",
        "stage_checkpointed",
        "stage_failed",
        "stage_lease_lost",
    }
)


class LocalExecutionError(ValueError):
    """Raised when local command execution is asked to act unsafely."""


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        return False
    return True


class LocalExecutionDiagnostics:
    """Bounded ID-and-code-only execution diagnostics.

    Free text, filesystem paths, tokens, provider payloads, prompts, and
    evidence content can never enter this record: every field name is
    allowlisted and every string value must be a UUID, a canonical stage, or a
    snake-case code.
    """

    def __init__(self, *, limit: int = 128) -> None:
        if type(limit) is not int or not 1 <= limit <= 1_024:
            raise LocalExecutionError("diagnostic limit must be between 1 and 1024")
        self._events: deque[dict[str, object]] = deque(maxlen=limit)

    def record(self, event: str, **fields: Any) -> None:
        if event not in _SAFE_DIAGNOSTIC_EVENTS:
            raise LocalExecutionError("diagnostic event is unsupported")
        recorded: dict[str, object] = {"event": event}
        for name, value in fields.items():
            if name not in _SAFE_DIAGNOSTIC_FIELDS:
                raise LocalExecutionError("diagnostic field is unsafe")
            recorded[name] = self._safe_value(value)
        self._events.append(recorded)

    def events(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(event) for event in self._events)

    @staticmethod
    def _safe_value(value: object) -> object:
        if value is None or type(value) is bool:
            return value
        if type(value) is int:
            if not 0 <= value <= 1_000_000:
                raise LocalExecutionError("diagnostic field is unsafe")
            return value
        if isinstance(value, str):
            if (
                value in STAGES
                or _is_uuid(value)
                or _SAFE_CODE_PATTERN.fullmatch(value) is not None
            ):
                return value
            raise LocalExecutionError("diagnostic field is unsafe")
        if isinstance(value, (tuple, list)):
            return [
                LocalExecutionDiagnostics._safe_value(item)
                for item in value
            ]
        raise LocalExecutionError("diagnostic field is unsafe")


@dataclass(frozen=True, slots=True)
class LocalExecutionOutcome:
    status: str
    command_id: str | None = None
    stage: str | None = None
    artifact_id: str | None = None
    error_code: str | None = None
    retryable: bool | None = None
    blocking_reason_codes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "blocking_reason_codes": list(self.blocking_reason_codes),
            "command_id": self.command_id,
            "contract_version": "local_research_command_outcome.v1",
            "error_code": self.error_code,
            "retryable": self.retryable,
            "stage": self.stage,
            "status": self.status,
        }


class EmbeddedPlanSecurityContextResolver:
    """Derives security context from one capture's own immutable source plan.

    The accepted capture archive embeds the exact hash-bound source plan that
    produced it. Reading identity from that plan keeps every Research Run bound
    to real capture provenance instead of a separately mutable directory. The
    operator still declares ticker and trusted issuer hosts, exactly as the
    offline acceptance CLI requires.
    """

    def __init__(
        self,
        *,
        repository: FilePrimarySourceCaptureRepository,
        ticker: str,
        trusted_issuer_hosts: tuple[str, ...],
    ) -> None:
        self._repository = repository
        self._ticker = ticker
        self._trusted_issuer_hosts = trusted_issuer_hosts

    def resolve(self, claim: CommitteeCommandClaim) -> AcceptedCaptureSecurityContext:
        archive = self._repository.read_archive(
            claim.operator_id,
            claim.capture_id,
            claim.capture_revision,
        )
        try:
            with ZipFile(BytesIO(archive)) as entries:
                info = entries.getinfo(EMBEDDED_PLAN_ENTRY)
                if info.is_dir() or (info.external_attr >> 16) & 0o120000 == 0o120000:
                    raise PrimarySourceStorageError(
                        "embedded source plan entry is invalid"
                    )
                plan = load_primary_source_plan(entries.read(info))
        except (BadZipFile, KeyError, OSError) as error:
            raise PrimarySourceStorageError(
                "accepted capture source plan is unavailable"
            ) from error
        except PrimarySourcePlanError as error:
            raise PrimarySourceStorageError(
                "accepted capture source plan is invalid"
            ) from error
        if plan.security_id != claim.security_id:
            raise PrimarySourceStorageError(
                "accepted capture source plan security does not match command"
            )
        return AcceptedCaptureSecurityContext(
            security_id=plan.security_id,
            cik=plan.cik,
            issuer_name=plan.issuer_name,
            ticker=self._ticker,
            primary_listing_exchange=plan.primary_listing_exchange,
            trusted_issuer_hosts=self._trusted_issuer_hosts,
        )


class LocalResearchCommandExecutor:
    """Bounded entrypoint that advances one local command by one stage."""

    def __init__(
        self,
        *,
        worker_id: str,
        commands: FileResearchRunCommandStore,
        stages: Mapping[str, ResearchRunStage],
        diagnostics: LocalExecutionDiagnostics | None = None,
        heartbeat_interval_seconds: float = 60.0,
        blocking_reasons: Mapping[str, tuple[str, ...]] = (
            LOCAL_STAGE_BLOCKING_REASONS
        ),
    ) -> None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise LocalExecutionError("worker_id is required")
        unsupported = sorted(set(stages) - set(STAGES))
        if unsupported:
            raise LocalExecutionError("local stage map is unsupported")
        self._worker_id = worker_id.strip()
        self._commands = commands
        self._stages = dict(stages)
        self._diagnostics = diagnostics
        self._blocking_reasons = dict(blocking_reasons)
        self._lease_keeper = ThreadedCommitteeLeaseKeeper(
            commands,
            interval_seconds=heartbeat_interval_seconds,
        )

    def run_once(self) -> LocalExecutionOutcome:
        claim = self._commands.claim_next(self._worker_id)
        if claim is None:
            return LocalExecutionOutcome(status="idle")
        self._record(
            "command_claimed",
            command_id=claim.command_id,
            stage=claim.next_stage,
            attempt_number=claim.attempt_number,
        )
        stage = self._stages.get(claim.next_stage)
        if stage is None:
            reasons = self._blocking_reasons.get(
                claim.next_stage,
                _DEFAULT_BLOCKING_REASONS,
            )
            self._commands.block(
                claim,
                stage=claim.next_stage,
                blocking_reason_codes=reasons,
            )
            self._record(
                "stage_blocked",
                command_id=claim.command_id,
                stage=claim.next_stage,
                blocking_reason_codes=reasons,
            )
            return LocalExecutionOutcome(
                status="blocked",
                command_id=claim.command_id,
                stage=claim.next_stage,
                blocking_reason_codes=tuple(reasons),
            )
        try:
            artifact_id = self._lease_keeper.execute(claim, stage)
        except CommitteeLeaseLostError:
            self._record(
                "stage_lease_lost",
                command_id=claim.command_id,
                stage=claim.next_stage,
            )
            return LocalExecutionOutcome(
                status="lease_lost",
                command_id=claim.command_id,
                stage=claim.next_stage,
            )
        except ResearchRunStageError as error:
            self._commands.fail(
                claim,
                stage=claim.next_stage,
                error_code=error.error_code,
                retryable=error.retryable,
            )
            self._record(
                "stage_failed",
                command_id=claim.command_id,
                stage=claim.next_stage,
                error_code=error.error_code,
                retryable=error.retryable,
            )
            return LocalExecutionOutcome(
                status="failed",
                command_id=claim.command_id,
                stage=claim.next_stage,
                error_code=error.error_code,
                retryable=error.retryable,
            )
        self._commands.checkpoint(
            claim,
            stage=claim.next_stage,
            artifact_id=artifact_id,
        )
        self._record(
            "stage_checkpointed",
            command_id=claim.command_id,
            stage=claim.next_stage,
            artifact_id=artifact_id,
        )
        return LocalExecutionOutcome(
            status="checkpointed",
            command_id=claim.command_id,
            stage=claim.next_stage,
            artifact_id=artifact_id,
        )

    def run_bounded(self, *, max_stages: int) -> tuple[LocalExecutionOutcome, ...]:
        if (
            type(max_stages) is not int
            or not 1 <= max_stages <= MAXIMUM_BOUNDED_STAGES
        ):
            raise LocalExecutionError(
                f"stage budget must be between 1 and {MAXIMUM_BOUNDED_STAGES}"
            )
        outcomes: list[LocalExecutionOutcome] = []
        for _ in range(max_stages):
            outcome = self.run_once()
            outcomes.append(outcome)
            if outcome.status != "checkpointed":
                break
        return tuple(outcomes)

    def _record(self, event: str, **fields: Any) -> None:
        if self._diagnostics is not None:
            self._diagnostics.record(event, **fields)


class DeclaredTrustedIssuerHostRegistry:
    """Serves the operator-declared trusted issuer hosts for local execution.

    The hosted registry keys hosts by security and workflow version because it
    serves many configurations at once. The local executor is composed for one
    operator with one declared host list, exactly as the offline acceptance CLI
    requires, so resolving is a pass-through. The declaration is still checked
    for emptiness here rather than assumed, because an empty list would let the
    evidence source treat any host as trusted.
    """

    def __init__(self, hosts: tuple[str, ...]) -> None:
        if not hosts or any(not str(host).strip() for host in hosts):
            raise LocalExecutionError("trusted issuer hosts are required")
        self._hosts = tuple(str(host).strip() for host in hosts)

    def resolve(self, research_run: Any) -> tuple[str, ...]:
        del research_run  # One declared list covers this operator's captures.
        return self._hosts


def compose_local_research_command_executor(
    *,
    worker_id: str,
    commands: FileResearchRunCommandStore,
    research_run_repository: Any,
    capture_repository: FilePrimarySourceCaptureRepository,
    ticker: str,
    trusted_issuer_hosts: tuple[str, ...],
    sec_user_agent: str,
    clock: Callable[[], datetime],
    evidence_bundle_repository: Any | None = None,
    diagnostics: LocalExecutionDiagnostics | None = None,
    heartbeat_interval_seconds: float = 60.0,
) -> LocalResearchCommandExecutor:
    """Compose the locally executable stages plus their blocked boundaries.

    `evidence_bundle_repository` is optional. Without a durable local Evidence
    Bundle store the `evidence_bundle` stage is not composed at all, and the
    command records the same explicit block it recorded before that store
    existed. Nothing is ever half-executed to fill the gap.
    """

    research_run_stage = compose_accepted_capture_research_run_stage(
        research_run_repository=research_run_repository,
        capture_repository=capture_repository,
        security_context_resolver=EmbeddedPlanSecurityContextResolver(
            repository=capture_repository,
            ticker=ticker,
            trusted_issuer_hosts=trusted_issuer_hosts,
        ),
        sec_user_agent=sec_user_agent,
        clock=clock,
    )
    stages: dict[str, ResearchRunStage] = {"research_run": research_run_stage}
    if evidence_bundle_repository is not None:
        # The stage resolves the Research Run itself and refuses any run whose
        # operator, security, cutoff, or workflow version differs from the
        # claim, so the bundle can only ever bind to the exact capture-bound
        # run this command already produced. The evidence itself is replayed
        # from that accepted capture: no provider, model, or network client is
        # constructed here.
        stages["evidence_bundle"] = compose_dynamic_persistent_evidence_bundle_stage(
            research_run_repository=research_run_repository,
            evidence_bundle_repository=evidence_bundle_repository,
            capture_repository=capture_repository,
            trusted_issuer_host_registry=DeclaredTrustedIssuerHostRegistry(
                trusted_issuer_hosts
            ),
            sec_user_agent=sec_user_agent,
            clock=clock,
        )
    return LocalResearchCommandExecutor(
        worker_id=worker_id,
        commands=commands,
        stages=stages,
        diagnostics=diagnostics,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )


def default_local_capture_root(repository_root: Path) -> Path:
    return Path(repository_root) / "data/primary-source-captures"


__all__ = [
    "DeclaredTrustedIssuerHostRegistry",
    "EmbeddedPlanSecurityContextResolver",
    "LOCAL_STAGE_BLOCKING_REASONS",
    "LocalExecutionDiagnostics",
    "LocalExecutionError",
    "LocalExecutionOutcome",
    "LocalResearchCommandExecutor",
    "compose_local_research_command_executor",
    "default_local_capture_root",
]
