from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event
import unittest
from uuid import NAMESPACE_URL, uuid5

from investment_research_os.production_execution import (
    LiveExecutionAuthorizationManifest,
    LiveMvpPreflightInputs,
)
from investment_research_os.production_execution.preflight import (
    PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
    PERSONAL_RESEARCH_VALUATION_CONTRACT_VERSION,
)
from investment_research_os.research_runs import (
    PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
    PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    QUESTION_TYPE_VERSION,
    WORKFLOW_CONFIG_VERSION,
)
from workers.research_committee.__main__ import (
    ResearchCommitteeStartupError,
    ResearchCommitteeWorkerDependencies,
    build_worker,
    load_startup_configuration,
)
from workers.research_committee.worker import (
    CommitteeCommandClaim,
    ResearchRunStageError,
)


STAGES = (
    "research_run",
    "evidence_bundle",
    "valuation_snapshot",
    "grader_committee",
    "committee_memo",
    "readiness_thesis",
)
NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def authorized_manifest() -> LiveExecutionAuthorizationManifest:
    return LiveExecutionAuthorizationManifest.freeze(
        authorization_id="auth-iro-058",
        operator_id="operator-1",
        turn_id="turn-iro-058",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=15),
        authorized_interactions=(
            "hosted_database",
            "live_primary_sources",
            "personal_market_data",
            "model_provider",
        ),
    )


def passing_preflight_inputs() -> LiveMvpPreflightInputs:
    return LiveMvpPreflightInputs(
        current_operator_id="operator-1",
        current_turn_id="turn-iro-058",
        checked_at=NOW,
        production_config_active=True,
        paid_evaluation_roles=(
            "grader:moonshot",
            "grader:catalyst",
            "grader:biotech",
            "grader:risk_dilution",
            "grader:valuation",
            "synthesizer",
        ),
        sample_memo_approved=True,
        licensed_official_close_rights=False,
        licensed_authenticated_display_rights=False,
        hosted_isolation_verified=True,
        estimated_run_cost_usd=Decimal("6.00"),
        run_budget_limit_usd=Decimal("7.00"),
        daily_budget_limit_usd=Decimal("14.00"),
        monthly_budget_limit_usd=Decimal("30.00"),
        run_budget_remaining_usd=Decimal("7.00"),
        daily_budget_remaining_usd=Decimal("14.00"),
        monthly_budget_remaining_usd=Decimal("30.00"),
        thesis_contract_id=PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
        valuation_contract_version=PERSONAL_RESEARCH_VALUATION_CONTRACT_VERSION,
        personal_research_valuation_pipeline_verified=True,
        nasdaq_trader_live_contract_verified=True,
    )


def valid_environment() -> dict[str, str]:
    return {
        "IROS_WORKER_ID": "committee-worker-local",
        "IROS_SUPABASE_URL": "https://example.supabase.co",
        "IROS_SUPABASE_SECRET_KEY": "private-secret-value",
        "SEC_USER_AGENT": "Investment Research OS test@example.com",
        "MASSIVE_API_KEY": "massive-private-key",
        "IROS_PRIMARY_SOURCE_CAPTURE_ROOT": "/tmp/iros-primary-source-captures",
    }


def stable_uuid(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"iros-worker-cli-tracer:{value}"))


class InMemoryCommandStore:
    def __init__(
        self,
        *,
        operator_id: str = "operator-1",
        question_type_version: str = PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
        workflow_config_version: str = PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    ) -> None:
        self.completed: list[str] = []
        self.checkpoints: list[tuple[str, str]] = []
        self.failures: list[tuple[str, str, bool]] = []
        self.research_run_id: str | None = None
        self.operator_id = operator_id
        self.question_type_version = question_type_version
        self.workflow_config_version = workflow_config_version

    def claim_next(self, worker_id: str) -> CommitteeCommandClaim | None:
        if len(self.completed) == len(STAGES):
            return None
        stage = STAGES[len(self.completed)]
        return CommitteeCommandClaim(
            command_id=stable_uuid("command"),
            operator_id=self.operator_id,
            security_id=stable_uuid("security"),
            question_type_version=self.question_type_version,
            workflow_config_version=self.workflow_config_version,
            as_of_cutoff=datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC),
            operator_focus=None,
            attempt_id=stable_uuid("attempt"),
            attempt_number=1,
            lease_token=stable_uuid("lease"),
            next_stage=stage,
            completed_stages=tuple(self.completed),
            research_run_id=self.research_run_id,
        )

    def renew_lease(self, claim: CommitteeCommandClaim) -> None:
        return None

    def checkpoint(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        artifact_id: str,
    ) -> None:
        self.completed.append(stage)
        self.checkpoints.append((stage, artifact_id))
        if stage == "research_run":
            self.research_run_id = artifact_id

    def fail(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        error_code: str,
        retryable: bool,
    ) -> None:
        self.failures.append((stage, error_code, retryable))


class FakeStage:
    def __init__(self, stage: str, calls: list[str]) -> None:
        self._stage = stage
        self._calls = calls

    def execute(self, claim: CommitteeCommandClaim) -> str:
        self._calls.append(self._stage)
        return stable_uuid(self._stage)


class FailingStage:
    def execute(self, claim: CommitteeCommandClaim) -> str:
        raise ResearchRunStageError(
            "research_run_persistence_failed",
            retryable=True,
        )


class WaitForLeaseRenewalStage:
    def __init__(self, renewal_attempted: Event) -> None:
        self._renewal_attempted = renewal_attempted

    def execute(self, claim: CommitteeCommandClaim) -> str:
        if not self._renewal_attempted.wait(timeout=1):
            raise AssertionError("lease renewal did not run")
        return stable_uuid("research_run")


class ResearchCommitteeWorkerTracerTests(unittest.TestCase):
    def test_startup_configuration_does_not_require_massive_for_injected_valuation(
        self,
    ) -> None:
        environment = valid_environment()
        del environment["MASSIVE_API_KEY"]

        configuration = load_startup_configuration(environment)

        self.assertIsNone(configuration.massive_api_key)

    def test_startup_configuration_exposes_primary_source_capture_root(self) -> None:
        configuration = load_startup_configuration(valid_environment())

        self.assertEqual(
            configuration.primary_source_capture_root,
            Path("/tmp/iros-primary-source-captures"),
        )

    def test_explicit_primary_source_capture_root_must_be_absolute(self) -> None:
        environment = valid_environment()
        environment["IROS_PRIMARY_SOURCE_CAPTURE_ROOT"] = "captures/primary"

        with self.assertRaisesRegex(
            ResearchCommitteeStartupError,
            "IROS_PRIMARY_SOURCE_CAPTURE_ROOT must be an absolute path",
        ):
            load_startup_configuration(environment)

    def test_default_primary_source_capture_root_is_cwd_independent(self) -> None:
        environment = valid_environment()
        del environment["IROS_PRIMARY_SOURCE_CAPTURE_ROOT"]

        configuration = load_startup_configuration(environment)

        self.assertTrue(configuration.primary_source_capture_root.is_absolute())
        self.assertEqual(
            configuration.primary_source_capture_root.name,
            "primary-source-captures",
        )

    def test_build_worker_runs_injected_persistent_stage_chain(self) -> None:
        store = InMemoryCommandStore()
        stage_calls: list[str] = []
        capture_roots: list[Path] = []
        stages = {stage: FakeStage(stage, stage_calls) for stage in STAGES}
        dependencies = ResearchCommitteeWorkerDependencies(
            commands=store,
            research_run_stage=stages["research_run"],
            evidence_bundle_stage_factory=lambda capture_root: (
                capture_roots.append(capture_root) or stages["evidence_bundle"]
            ),
            valuation_snapshot_stage=stages["valuation_snapshot"],
            grader_committee_stage=stages["grader_committee"],
            committee_memo_stage=stages["committee_memo"],
            readiness_thesis_stage=stages["readiness_thesis"],
            authorization_manifest=authorized_manifest(),
            preflight_inputs=passing_preflight_inputs(),
            clock=lambda: NOW,
        )

        worker = build_worker(
            load_startup_configuration(valid_environment()),
            dependencies=dependencies,
        )
        while worker.run_once():
            pass

        self.assertEqual(stage_calls, list(STAGES))
        self.assertEqual(
            capture_roots,
            [Path("/tmp/iros-primary-source-captures")],
        )
        self.assertEqual(
            [stage for stage, _artifact_id in store.checkpoints],
            list(STAGES),
        )
        self.assertEqual(store.failures, [])

    def test_build_worker_stops_before_stages_when_gate_is_missing(self) -> None:
        store = InMemoryCommandStore()
        stage_calls: list[str] = []
        stages = {stage: FakeStage(stage, stage_calls) for stage in STAGES}
        dependencies = ResearchCommitteeWorkerDependencies(
            commands=store,
            research_run_stage=stages["research_run"],
            evidence_bundle_stage_factory=lambda capture_root: stages[
                "evidence_bundle"
            ],
            valuation_snapshot_stage=stages["valuation_snapshot"],
            grader_committee_stage=stages["grader_committee"],
            committee_memo_stage=stages["committee_memo"],
            readiness_thesis_stage=stages["readiness_thesis"],
            authorization_manifest=authorized_manifest(),
            preflight_inputs=replace(
                passing_preflight_inputs(),
                hosted_isolation_verified=False,
            ),
            clock=lambda: NOW,
        )

        with self.assertRaisesRegex(
            ResearchCommitteeStartupError,
            "hosted_isolation_not_verified",
        ):
            build_worker(
                load_startup_configuration(valid_environment()),
                dependencies=dependencies,
            )

        self.assertEqual(stage_calls, [])
        self.assertEqual(store.checkpoints, [])

    def test_worker_rejects_claim_outside_authorized_operator(self) -> None:
        store = InMemoryCommandStore(operator_id="operator-2")
        stage_calls: list[str] = []
        stages = {stage: FakeStage(stage, stage_calls) for stage in STAGES}
        dependencies = ResearchCommitteeWorkerDependencies(
            commands=store,
            research_run_stage=stages["research_run"],
            evidence_bundle_stage_factory=lambda capture_root: stages[
                "evidence_bundle"
            ],
            valuation_snapshot_stage=stages["valuation_snapshot"],
            grader_committee_stage=stages["grader_committee"],
            committee_memo_stage=stages["committee_memo"],
            readiness_thesis_stage=stages["readiness_thesis"],
            authorization_manifest=authorized_manifest(),
            preflight_inputs=passing_preflight_inputs(),
            clock=lambda: NOW,
        )
        worker = build_worker(
            load_startup_configuration(valid_environment()),
            dependencies=dependencies,
        )

        with self.assertRaisesRegex(
            ResearchCommitteeStartupError,
            "claim outside live authorization",
        ):
            worker.run_once()

        self.assertEqual(stage_calls, [])
        self.assertEqual(store.checkpoints, [])
        self.assertEqual(
            store.failures,
            [
                (
                    "research_run",
                    "live_execution_authorization_claim_mismatch",
                    False,
                )
            ],
        )

    def test_personal_authorization_rejects_strict_workflow_claim(self) -> None:
        store = InMemoryCommandStore(
            question_type_version=QUESTION_TYPE_VERSION,
            workflow_config_version=WORKFLOW_CONFIG_VERSION,
        )
        stage_calls: list[str] = []
        stages = {stage: FakeStage(stage, stage_calls) for stage in STAGES}
        dependencies = ResearchCommitteeWorkerDependencies(
            commands=store,
            research_run_stage=stages["research_run"],
            evidence_bundle_stage_factory=lambda capture_root: stages[
                "evidence_bundle"
            ],
            valuation_snapshot_stage=stages["valuation_snapshot"],
            grader_committee_stage=stages["grader_committee"],
            committee_memo_stage=stages["committee_memo"],
            readiness_thesis_stage=stages["readiness_thesis"],
            authorization_manifest=authorized_manifest(),
            preflight_inputs=passing_preflight_inputs(),
            clock=lambda: NOW,
        )
        worker = build_worker(
            load_startup_configuration(valid_environment()),
            dependencies=dependencies,
        )

        with self.assertRaisesRegex(
            ResearchCommitteeStartupError,
            "claim outside live authorization",
        ):
            worker.run_once()

        self.assertEqual(stage_calls, [])
        self.assertEqual(
            store.failures,
            [
                (
                    "research_run",
                    "live_execution_authorization_claim_mismatch",
                    False,
                )
            ],
        )

    def test_worker_rechecks_authorization_expiry_before_each_claim(self) -> None:
        store = InMemoryCommandStore()
        stage_calls: list[str] = []
        stages = {stage: FakeStage(stage, stage_calls) for stage in STAGES}
        current_time = [NOW]
        dependencies = ResearchCommitteeWorkerDependencies(
            commands=store,
            research_run_stage=stages["research_run"],
            evidence_bundle_stage_factory=lambda capture_root: stages[
                "evidence_bundle"
            ],
            valuation_snapshot_stage=stages["valuation_snapshot"],
            grader_committee_stage=stages["grader_committee"],
            committee_memo_stage=stages["committee_memo"],
            readiness_thesis_stage=stages["readiness_thesis"],
            authorization_manifest=authorized_manifest(),
            preflight_inputs=passing_preflight_inputs(),
            clock=lambda: current_time[0],
        )
        worker = build_worker(
            load_startup_configuration(valid_environment()),
            dependencies=dependencies,
        )

        self.assertTrue(worker.run_once())
        current_time[0] = NOW + timedelta(minutes=20)
        with self.assertRaisesRegex(
            ResearchCommitteeStartupError,
            "authorization_expired",
        ):
            worker.run_once()

        self.assertEqual(stage_calls, ["research_run"])
        self.assertEqual(len(store.checkpoints), 1)

    def test_expiry_during_lease_renewal_prevents_checkpoint(self) -> None:
        store = InMemoryCommandStore()
        stage_calls: list[str] = []
        stages = {stage: FakeStage(stage, stage_calls) for stage in STAGES}
        renewal_attempted = Event()
        clock_calls = 0

        def expiring_clock() -> datetime:
            nonlocal clock_calls
            clock_calls += 1
            if clock_calls >= 3:
                renewal_attempted.set()
                return NOW + timedelta(minutes=20)
            return NOW

        dependencies = ResearchCommitteeWorkerDependencies(
            commands=store,
            research_run_stage=WaitForLeaseRenewalStage(renewal_attempted),
            evidence_bundle_stage_factory=lambda capture_root: stages[
                "evidence_bundle"
            ],
            valuation_snapshot_stage=stages["valuation_snapshot"],
            grader_committee_stage=stages["grader_committee"],
            committee_memo_stage=stages["committee_memo"],
            readiness_thesis_stage=stages["readiness_thesis"],
            authorization_manifest=authorized_manifest(),
            preflight_inputs=passing_preflight_inputs(),
            clock=expiring_clock,
            heartbeat_interval_seconds=0.001,
        )
        worker = build_worker(
            load_startup_configuration(valid_environment()),
            dependencies=dependencies,
        )

        self.assertTrue(worker.run_once())

        self.assertTrue(renewal_attempted.is_set())
        self.assertEqual(store.checkpoints, [])

    def test_build_worker_records_bounded_stage_failure(self) -> None:
        store = InMemoryCommandStore()
        stage_calls: list[str] = []
        stages = {stage: FakeStage(stage, stage_calls) for stage in STAGES}
        dependencies = ResearchCommitteeWorkerDependencies(
            commands=store,
            research_run_stage=FailingStage(),
            evidence_bundle_stage_factory=lambda capture_root: stages[
                "evidence_bundle"
            ],
            valuation_snapshot_stage=stages["valuation_snapshot"],
            grader_committee_stage=stages["grader_committee"],
            committee_memo_stage=stages["committee_memo"],
            readiness_thesis_stage=stages["readiness_thesis"],
            authorization_manifest=authorized_manifest(),
            preflight_inputs=passing_preflight_inputs(),
            clock=lambda: NOW,
        )
        worker = build_worker(
            load_startup_configuration(valid_environment()),
            dependencies=dependencies,
        )

        self.assertTrue(worker.run_once())

        self.assertEqual(store.checkpoints, [])
        self.assertEqual(
            store.failures,
            [("research_run", "research_run_persistence_failed", True)],
        )


if __name__ == "__main__":
    unittest.main()
