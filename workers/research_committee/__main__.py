from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
import os
from pathlib import Path
import sys
import time
from typing import TextIO

from investment_research_os.production_execution import (
    LiveExecutionAuthorizationManifest,
    LiveMvpPreflightInputs,
    evaluate_live_mvp_preflight,
)
from investment_research_os.research_runs import (
    PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
    PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
    PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    QUESTION_TYPE_VERSION,
    THESIS_CONTRACT_ID,
    WORKFLOW_CONFIG_VERSION,
)

from .composition import compose_persistent_committee_worker
from .runner import (
    ResearchCommitteeRunner,
    ResearchCommitteeWorker,
    validate_poll_interval_seconds,
)
from .worker import CommitteeCommandClaim, CommitteeCommandStore, ResearchRunStage


_USAGE = (
    "usage: python3 -m workers.research_committee [--once] [--poll-seconds 0.1..60]"
)
_REQUIRED_ENVIRONMENT = (
    "IROS_WORKER_ID",
    "IROS_SUPABASE_URL",
    "IROS_SUPABASE_SECRET_KEY",
    "SEC_USER_AGENT",
)
_PRIMARY_SOURCE_CAPTURE_ROOT_ENVIRONMENT = "IROS_PRIMARY_SOURCE_CAPTURE_ROOT"
_DEFAULT_PRIMARY_SOURCE_CAPTURE_ROOT = (
    Path(__file__).resolve().parents[2] / "data/primary-source-captures"
)
_MISSING_PRODUCTION_COMPOSITION = (
    "nasdaq_trader_live_contract_verification",
    "personal_research_market_activation",
    "approved_model_provider_activation",
    "live_execution_authorization_manifest",
    "hosted_isolation_verification",
)
_RUN_CONTRACT_BY_THESIS = {
    THESIS_CONTRACT_ID: (QUESTION_TYPE_VERSION, WORKFLOW_CONFIG_VERSION),
    PERSONAL_RESEARCH_THESIS_CONTRACT_ID: (
        PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
        PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    ),
}


class ResearchCommitteeStartupError(ValueError):
    """Raised when a complete, safe worker cannot be started."""


@dataclass(frozen=True, slots=True)
class ResearchCommitteeStartupConfiguration:
    worker_id: str
    supabase_url: str
    supabase_secret_key: str
    sec_user_agent: str
    massive_api_key: str | None
    primary_source_capture_root: Path

    def __repr__(self) -> str:
        return (
            "ResearchCommitteeStartupConfiguration("
            f"worker_id={self.worker_id!r}, "
            f"supabase_url={self.supabase_url!r}, "
            "supabase_secret_key=<redacted>, "
            f"sec_user_agent={self.sec_user_agent!r}, "
            f"primary_source_capture_root={self.primary_source_capture_root!r}, "
            "massive_api_key="
            f"{'<configured>' if self.massive_api_key else '<inactive>'})"
        )


@dataclass(frozen=True, slots=True)
class ResearchCommitteeWorkerDependencies:
    commands: CommitteeCommandStore
    research_run_stage: ResearchRunStage
    evidence_bundle_stage_factory: Callable[[Path], ResearchRunStage]
    valuation_snapshot_stage: ResearchRunStage
    grader_committee_stage: ResearchRunStage
    committee_memo_stage: ResearchRunStage
    readiness_thesis_stage: ResearchRunStage
    authorization_manifest: LiveExecutionAuthorizationManifest
    preflight_inputs: LiveMvpPreflightInputs
    clock: Callable[[], datetime]
    heartbeat_interval_seconds: float = 60.0


def _assert_live_mvp_preflight(
    *,
    manifest: LiveExecutionAuthorizationManifest,
    inputs: LiveMvpPreflightInputs,
    checked_at: datetime,
) -> None:
    decision = evaluate_live_mvp_preflight(
        manifest=manifest,
        inputs=replace(inputs, checked_at=checked_at),
    )
    if (
        not decision.allowed
        or decision.blocking_reason_codes
        or decision.permitted_interactions != manifest.authorized_interactions
        or decision.authorization_manifest_sha256 != manifest.content_sha256
    ):
        reasons = decision.blocking_reason_codes or ("live_mvp_preflight_invalid",)
        raise ResearchCommitteeStartupError(
            "research committee live MVP preflight blocked: " + ", ".join(reasons)
        )


class _AuthorizationScopedCommandStore:
    def __init__(
        self,
        *,
        commands: CommitteeCommandStore,
        manifest: LiveExecutionAuthorizationManifest,
        preflight_inputs: LiveMvpPreflightInputs,
        clock: Callable[[], datetime],
    ) -> None:
        self._commands = commands
        self._manifest = manifest
        self._preflight_inputs = preflight_inputs
        self._clock = clock

    def _assert_current(self) -> None:
        _assert_live_mvp_preflight(
            manifest=self._manifest,
            inputs=self._preflight_inputs,
            checked_at=self._clock(),
        )

    def claim_next(self, worker_id: str) -> CommitteeCommandClaim | None:
        self._assert_current()
        claim = self._commands.claim_next(worker_id)
        if claim is None:
            return None
        expected_contract = _RUN_CONTRACT_BY_THESIS.get(
            self._preflight_inputs.thesis_contract_id
        )
        if (
            claim.operator_id != self._manifest.operator_id
            or expected_contract is None
            or (claim.question_type_version, claim.workflow_config_version)
            != expected_contract
        ):
            self._commands.fail(
                claim,
                stage=claim.next_stage,
                error_code="live_execution_authorization_claim_mismatch",
                retryable=False,
            )
            raise ResearchCommitteeStartupError(
                "research committee claim outside live authorization"
            )
        return claim

    def renew_lease(self, claim: CommitteeCommandClaim) -> None:
        self._assert_current()
        self._commands.renew_lease(claim)

    def checkpoint(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        artifact_id: str,
    ) -> None:
        self._assert_current()
        self._commands.checkpoint(claim, stage=stage, artifact_id=artifact_id)

    def fail(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        error_code: str,
        retryable: bool,
    ) -> None:
        self._commands.fail(
            claim,
            stage=stage,
            error_code=error_code,
            retryable=retryable,
        )


@dataclass(frozen=True, slots=True)
class _CliOptions:
    once: bool
    poll_interval_seconds: float


def load_startup_configuration(
    environment: Mapping[str, str],
) -> ResearchCommitteeStartupConfiguration:
    values = {name: environment.get(name, "").strip() for name in _REQUIRED_ENVIRONMENT}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ResearchCommitteeStartupError(
            "missing required environment variables: " + ", ".join(missing)
        )
    capture_root_value = environment.get(
        _PRIMARY_SOURCE_CAPTURE_ROOT_ENVIRONMENT,
        "",
    ).strip()
    capture_root = (
        Path(capture_root_value).expanduser()
        if capture_root_value
        else _DEFAULT_PRIMARY_SOURCE_CAPTURE_ROOT
    )
    if capture_root_value and not capture_root.is_absolute():
        raise ResearchCommitteeStartupError(
            "IROS_PRIMARY_SOURCE_CAPTURE_ROOT must be an absolute path"
        )
    return ResearchCommitteeStartupConfiguration(
        worker_id=values["IROS_WORKER_ID"],
        supabase_url=values["IROS_SUPABASE_URL"],
        supabase_secret_key=values["IROS_SUPABASE_SECRET_KEY"],
        sec_user_agent=values["SEC_USER_AGENT"],
        massive_api_key=environment.get("MASSIVE_API_KEY", "").strip() or None,
        primary_source_capture_root=capture_root,
    )


def build_worker(
    configuration: ResearchCommitteeStartupConfiguration,
    *,
    dependencies: ResearchCommitteeWorkerDependencies | None = None,
) -> ResearchCommitteeWorker:
    if dependencies is None:
        raise ResearchCommitteeStartupError(
            "research committee production composition unavailable: "
            + ", ".join(_MISSING_PRODUCTION_COMPOSITION)
        )
    _assert_live_mvp_preflight(
        manifest=dependencies.authorization_manifest,
        inputs=dependencies.preflight_inputs,
        checked_at=dependencies.clock(),
    )
    evidence_bundle_stage = dependencies.evidence_bundle_stage_factory(
        configuration.primary_source_capture_root
    )
    commands = _AuthorizationScopedCommandStore(
        commands=dependencies.commands,
        manifest=dependencies.authorization_manifest,
        preflight_inputs=dependencies.preflight_inputs,
        clock=dependencies.clock,
    )
    return compose_persistent_committee_worker(
        worker_id=configuration.worker_id,
        commands=commands,
        research_run_stage=dependencies.research_run_stage,
        evidence_bundle_stage=evidence_bundle_stage,
        valuation_snapshot_stage=dependencies.valuation_snapshot_stage,
        grader_committee_stage=dependencies.grader_committee_stage,
        committee_memo_stage=dependencies.committee_memo_stage,
        readiness_thesis_stage=dependencies.readiness_thesis_stage,
        heartbeat_interval_seconds=dependencies.heartbeat_interval_seconds,
    )


def _parse_options(argv: list[str]) -> _CliOptions:
    once = False
    poll_interval_seconds = 2.0
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--once" and not once:
            once = True
            index += 1
            continue
        if argument == "--poll-seconds" and index + 1 < len(argv):
            try:
                poll_interval_seconds = float(argv[index + 1])
            except ValueError as error:
                raise ResearchCommitteeStartupError(_USAGE) from error
            index += 2
            continue
        raise ResearchCommitteeStartupError(_USAGE)
    return _CliOptions(
        once=once,
        poll_interval_seconds=validate_poll_interval_seconds(poll_interval_seconds),
    )


def run(
    argv: list[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    worker_factory: Callable[
        [ResearchCommitteeStartupConfiguration],
        ResearchCommitteeWorker,
    ] = build_worker,
    stderr: TextIO = sys.stderr,
    sleeper: Callable[[float], object] = time.sleep,
    stop_requested: Callable[[], bool] = lambda: False,
) -> int:
    try:
        options = _parse_options(argv or [])
        configuration = load_startup_configuration(
            os.environ if environment is None else environment
        )
        worker = worker_factory(configuration)
        ResearchCommitteeRunner(
            worker,
            poll_interval_seconds=options.poll_interval_seconds,
            sleeper=sleeper,
        ).run(once=options.once, stop_requested=stop_requested)
        return 0
    except KeyboardInterrupt:
        return 0
    except (ResearchCommitteeStartupError, ValueError) as error:
        print(f"error: {error}", file=stderr)
        return 2
    except Exception:
        print("error: research committee worker failed", file=stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
