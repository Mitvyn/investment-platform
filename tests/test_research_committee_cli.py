from __future__ import annotations

import io
import unittest

from workers.research_committee.__main__ import run


def valid_environment() -> dict[str, str]:
    return {
        "IROS_WORKER_ID": "committee-worker-local",
        "IROS_SUPABASE_URL": "https://example.supabase.co",
        "IROS_SUPABASE_SECRET_KEY": "private-secret-value",
        "SEC_USER_AGENT": "Investment Research OS test@example.com",
        "MASSIVE_API_KEY": "massive-private-key",
    }


class WorkerFake:
    def __init__(
        self,
        results: list[bool] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._results = results or [True]
        self._error = error
        self.calls = 0

    def run_once(self) -> bool:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._results.pop(0)


class ResearchCommitteeCliTests(unittest.TestCase):
    def test_missing_environment_stops_before_worker_factory(self) -> None:
        factory_calls: list[object] = []
        stderr = io.StringIO()

        exit_code = run(
            ["--once"],
            environment={},
            worker_factory=lambda config: factory_calls.append(config),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(factory_calls, [])
        self.assertIn("IROS_WORKER_ID", stderr.getvalue())
        self.assertIn("IROS_SUPABASE_URL", stderr.getvalue())
        self.assertNotIn("MASSIVE_API_KEY", stderr.getvalue())
        self.assertNotIn("secret_key=", stderr.getvalue())

    def test_once_executes_injected_complete_worker_once(self) -> None:
        worker = WorkerFake([True, True])
        sleeps: list[float] = []

        exit_code = run(
            ["--once"],
            environment=valid_environment(),
            worker_factory=lambda config: worker,
            sleeper=sleeps.append,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(worker.calls, 1)
        self.assertEqual(sleeps, [])

    def test_invalid_poll_interval_stops_before_worker_factory(self) -> None:
        factory_calls: list[object] = []
        stderr = io.StringIO()

        exit_code = run(
            ["--poll-seconds", "60.01"],
            environment=valid_environment(),
            worker_factory=lambda config: factory_calls.append(config),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(factory_calls, [])
        self.assertIn(
            "poll interval must be between 0.1 and 60 seconds",
            stderr.getvalue(),
        )

    def test_default_factory_reports_incomplete_production_composition(self) -> None:
        stderr = io.StringIO()

        exit_code = run(
            ["--once"],
            environment=valid_environment(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertIn(
            "research committee production composition unavailable",
            stderr.getvalue(),
        )
        self.assertIn(
            "nasdaq_trader_live_contract_verification",
            stderr.getvalue(),
        )
        self.assertIn(
            "personal_research_market_activation",
            stderr.getvalue(),
        )
        self.assertNotIn("approved_valuation_source_activation", stderr.getvalue())
        self.assertIn(
            "approved_model_provider_activation",
            stderr.getvalue(),
        )
        self.assertIn(
            "live_execution_authorization_manifest",
            stderr.getvalue(),
        )
        self.assertIn(
            "hosted_isolation_verification",
            stderr.getvalue(),
        )
        for resolved_blocker in (
            "dynamic_evidence_bundle_stage_factory",
            "licensed_valuation_snapshot_stage",
            "personal_research_market_calendar",
            "personal_research_historical_halt_verification",
            "personal_research_capital_evidence_adapter",
            "personal_research_corporate_action_adapter",
            "grader_committee_runtime_factory",
            "atomic_synthesis_budget_runtime",
            "committee_memo_runtime_sql",
            "readiness_thesis_runtime_sql",
        ):
            self.assertNotIn(resolved_blocker, stderr.getvalue())
        self.assertNotIn("private-secret-value", stderr.getvalue())
        self.assertNotIn("massive-private-key", stderr.getvalue())

    def test_unexpected_worker_error_is_redacted(self) -> None:
        stderr = io.StringIO()

        exit_code = run(
            ["--once"],
            environment=valid_environment(),
            worker_factory=lambda config: WorkerFake(
                error=RuntimeError("private provider detail")
            ),
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertIn(
            "error: research committee worker failed",
            stderr.getvalue(),
        )
        self.assertNotIn("private provider detail", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
