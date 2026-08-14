from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

from investment_research_os.research_runs import (
    ResearchRun,
    ResearchRunRepository,
    ResearchRunRequestError,
    ResearchRunWorkflow,
    SecurityEligibilitySnapshot,
)
from workers.primary_sources.evidence_source import ReplayEvidenceCandidateAssembler
from workers.primary_sources.models import PrimarySourceRequest
from workers.primary_sources.pipeline import PrimarySourcePipelineResult
from workers.primary_sources.storage import (
    FilePrimarySourceCaptureRepository,
    PersistedPrimarySourceCapture,
    PrimarySourceRunArtifactBinding,
    PrimarySourceStorageError,
)
from workers.sec.storage import EvidenceStorageError

from .worker import (
    CommitteeCommandClaim,
    PersistentResearchRunStage,
    ResearchRunStageError,
)


@dataclass(frozen=True, slots=True)
class AcceptedCaptureResearchInput:
    capture: PersistedPrimarySourceCapture
    request: PrimarySourceRequest
    ticker: str
    trusted_issuer_hosts: tuple[str, ...]

    def __post_init__(self) -> None:
        ticker = self.ticker.strip().upper()
        hosts = tuple(host.strip().lower() for host in self.trusted_issuer_hosts)
        if not ticker:
            raise ValueError("accepted capture ticker is required")
        if not hosts or any(not host for host in hosts):
            raise ValueError("accepted capture trusted issuer hosts are required")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "trusted_issuer_hosts", hosts)


class AcceptedCaptureResearchInputResolver(Protocol):
    def resolve(
        self,
        claim: CommitteeCommandClaim,
    ) -> AcceptedCaptureResearchInput: ...


class PipelineResultAssembler(Protocol):
    def assemble_result(
        self,
        raw_archive: bytes,
        *,
        request: PrimarySourceRequest,
        ticker: str,
        sec_user_agent: str,
        trusted_issuer_hosts: tuple[str, ...],
        accepted_at: datetime,
    ) -> PrimarySourcePipelineResult: ...


class _AcceptedCaptureReplayError(RuntimeError):
    def __init__(self, error_code: str, *, retryable: bool) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


class _LazyCaptureEligibilitySource:
    def __init__(
        self,
        *,
        repository: FilePrimarySourceCaptureRepository,
        value: AcceptedCaptureResearchInput,
        assembler: PipelineResultAssembler,
        sec_user_agent: str,
    ) -> None:
        self._repository = repository
        self._value = value
        self._assembler = assembler
        self._sec_user_agent = sec_user_agent
        self._result: PrimarySourcePipelineResult | None = None

    def load(
        self,
        operator_id: str,
        security_id: str,
        as_of_cutoff: datetime,
    ) -> SecurityEligibilitySnapshot:
        request = self._value.request
        if (
            operator_id != request.operator_id
            or security_id != request.security_id
            or as_of_cutoff != request.as_of_cutoff
        ):
            raise ResearchRunRequestError(
                "accepted capture eligibility request identity mismatch"
            )
        return self.result().eligibility_snapshot

    def result(self) -> PrimarySourcePipelineResult:
        if self._result is None:
            try:
                result = self._assembler.assemble_result(
                    self._repository.read_archive(
                        self._value.capture.operator_id,
                        self._value.capture.capture_id,
                        self._value.capture.capture_revision,
                    ),
                    request=self._value.request,
                    ticker=self._value.ticker,
                    sec_user_agent=self._sec_user_agent,
                    trusted_issuer_hosts=self._value.trusted_issuer_hosts,
                    accepted_at=self._value.capture.accepted_at,
                )
            except OSError as error:
                raise _AcceptedCaptureReplayError(
                    "research_run_accepted_capture_replay_unavailable",
                    retryable=True,
                ) from error
            except (PrimarySourceStorageError, ValueError) as error:
                raise _AcceptedCaptureReplayError(
                    "research_run_accepted_capture_replay_invalid",
                    retryable=False,
                ) from error
            snapshot = result.eligibility_snapshot
            request = self._value.request
            if (
                snapshot.security_id != request.security_id
                or snapshot.as_of_cutoff != request.as_of_cutoff
                or snapshot.cik != request.cik
                or snapshot.issuer_name != request.issuer_name
                or snapshot.display_symbol != self._value.ticker
                or snapshot.primary_listing_exchange != request.primary_listing_exchange
                or result.bundle_candidate.security_id != request.security_id
                or result.bundle_candidate.as_of_cutoff != request.as_of_cutoff
            ):
                raise _AcceptedCaptureReplayError(
                    "research_run_accepted_capture_replay_invalid",
                    retryable=False,
                )
            self._result = result
        return self._result


class AcceptedCaptureResearchRunStage:
    """Creates one Research Run from, then binds, one exact accepted capture."""

    def __init__(
        self,
        *,
        research_run_repository: ResearchRunRepository,
        capture_repository: FilePrimarySourceCaptureRepository,
        capture_resolver: AcceptedCaptureResearchInputResolver,
        sec_user_agent: str,
        clock: Callable[[], datetime],
        assembler: PipelineResultAssembler | None = None,
    ) -> None:
        if not sec_user_agent.strip():
            raise ValueError("SEC user agent is required")
        self._research_runs = research_run_repository
        self._captures = capture_repository
        self._capture_resolver = capture_resolver
        self._sec_user_agent = sec_user_agent
        self._clock = clock
        self._assembler = assembler or ReplayEvidenceCandidateAssembler()

    def execute(self, claim: CommitteeCommandClaim) -> str:
        try:
            value = self._capture_resolver.resolve(claim)
            self._validate_input(claim, value)
            stored_capture = self._captures.get_capture(
                value.capture.operator_id,
                value.capture.capture_id,
                value.capture.capture_revision,
            )
            if stored_capture != value.capture:
                raise PrimarySourceStorageError(
                    "accepted capture metadata is not the persisted artifact"
                )
        except OSError as error:
            raise ResearchRunStageError(
                "research_run_accepted_capture_unavailable",
                retryable=True,
            ) from error
        except (PrimarySourceStorageError, ValueError) as error:
            raise ResearchRunStageError(
                "research_run_accepted_capture_invalid",
                retryable=False,
            ) from error

        eligibility_source = _LazyCaptureEligibilitySource(
            repository=self._captures,
            value=value,
            assembler=self._assembler,
            sec_user_agent=self._sec_user_agent,
        )
        workflow = ResearchRunWorkflow(
            repository=self._research_runs,
            eligibility_source=eligibility_source,
            clock=self._clock,
        )
        try:
            run_id = PersistentResearchRunStage(workflow).execute(claim)
        except _AcceptedCaptureReplayError as error:
            raise ResearchRunStageError(
                error.error_code,
                retryable=error.retryable,
            ) from error
        try:
            run = self._research_runs.get(claim.operator_id, run_id)
        except EvidenceStorageError as error:
            raise ResearchRunStageError(
                "research_run_persistence_failed",
                retryable=True,
            ) from error
        if run is None:
            raise ResearchRunStageError(
                "research_run_persistence_failed",
                retryable=True,
            )

        try:
            binding = self._captures.get_for_run(claim.operator_id, run_id)
            if binding is None:
                evidence_policy_version = (
                    eligibility_source.result().bundle_candidate.evidence_policy_version
                )
                binding = self._captures.bind_to_run(
                    value.capture,
                    run,
                    evidence_policy_version=evidence_policy_version,
                    bound_at=self._clock(),
                )
            self._validate_binding(run, value, binding)
        except OSError as error:
            raise ResearchRunStageError(
                "research_run_capture_binding_unavailable",
                retryable=True,
            ) from error
        except (PrimarySourceStorageError, ResearchRunRequestError) as error:
            raise ResearchRunStageError(
                "research_run_capture_binding_invalid",
                retryable=False,
            ) from error
        return run_id

    @staticmethod
    def _validate_input(
        claim: CommitteeCommandClaim,
        value: AcceptedCaptureResearchInput,
    ) -> None:
        capture = value.capture
        request = value.request
        if (
            capture.operator_id != claim.operator_id
            or capture.security_id != claim.security_id
            or capture.as_of_cutoff != claim.as_of_cutoff
            or capture.question_type_version != claim.question_type_version
            or capture.workflow_config_version != claim.workflow_config_version
            or request.operator_id != claim.operator_id
            or request.security_id != claim.security_id
            or request.as_of_cutoff != claim.as_of_cutoff
        ):
            raise ValueError("accepted capture does not match command")

    @staticmethod
    def _validate_binding(
        run: ResearchRun,
        value: AcceptedCaptureResearchInput,
        binding: PrimarySourceRunArtifactBinding,
    ) -> None:
        capture = value.capture
        request = value.request
        if (
            binding.operator_id != run.operator_id
            or binding.research_run_id != run.id
            or binding.security_id != run.security_id
            or binding.as_of_cutoff != run.as_of_cutoff
            or binding.question_type != run.question_type
            or binding.question_type_version != run.question_type_version
            or binding.workflow_config_version != run.workflow_config_version
            or binding.thesis_contract_id != run.thesis_contract_id
            or binding.capture_id != capture.capture_id
            or binding.capture_revision != capture.capture_revision
            or binding.package_sha256 != capture.package_sha256
            or binding.capture_content_hash != capture.capture_content_hash
            or binding.plan_id != capture.plan_id
            or binding.plan_revision != capture.plan_revision
            or binding.plan_content_hash != capture.plan_content_hash
            or run.security_identity.cik != request.cik
            or run.security_identity.issuer_name != request.issuer_name
            or run.security_identity.symbol != value.ticker
            or run.security_identity.primary_listing_exchange
            != request.primary_listing_exchange
        ):
            raise PrimarySourceStorageError(
                "accepted capture binding does not match Research Run"
            )


__all__ = [
    "AcceptedCaptureResearchInput",
    "AcceptedCaptureResearchInputResolver",
    "AcceptedCaptureResearchRunStage",
    "PipelineResultAssembler",
]
