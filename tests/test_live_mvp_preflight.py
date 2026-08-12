from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from investment_research_os.production_execution import (
    LiveExecutionAuthorizationManifest,
    LiveMvpPreflightInputs,
    evaluate_live_mvp_preflight,
    prove_two_security_shared_contract,
)


NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def passing_inputs() -> LiveMvpPreflightInputs:
    return LiveMvpPreflightInputs(
        current_operator_id="operator-1",
        current_turn_id="turn-iro-041",
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
        licensed_official_close_rights=True,
        licensed_authenticated_display_rights=True,
        hosted_isolation_verified=True,
        estimated_run_cost_usd=Decimal("6.00"),
        run_budget_limit_usd=Decimal("7.00"),
        daily_budget_limit_usd=Decimal("14.00"),
        monthly_budget_limit_usd=Decimal("30.00"),
        run_budget_remaining_usd=Decimal("7.00"),
        daily_budget_remaining_usd=Decimal("14.00"),
        monthly_budget_remaining_usd=Decimal("30.00"),
    )


def authorized_manifest(
    *,
    turn_id: str = "turn-iro-041",
    issued_at: datetime = NOW - timedelta(minutes=1),
    expires_at: datetime = NOW + timedelta(minutes=15),
    interactions: tuple[str, ...] = (
        "hosted_database",
        "live_primary_sources",
        "licensed_market_data",
        "model_provider",
    ),
) -> LiveExecutionAuthorizationManifest:
    return LiveExecutionAuthorizationManifest.freeze(
        authorization_id="auth-iro-041",
        operator_id="operator-1",
        turn_id=turn_id,
        issued_at=issued_at,
        expires_at=expires_at,
        authorized_interactions=interactions,
    )


class LiveMvpPreflightTests(unittest.TestCase):
    def test_missing_authorization_manifest_fails_closed(self) -> None:
        decision = evaluate_live_mvp_preflight(
            manifest=None,
            inputs=passing_inputs(),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.blocking_reason_codes,
            ("authorization_manifest_missing",),
        )
        self.assertEqual(decision.permitted_interactions, ())

    def test_authorization_manifest_is_immutable_and_content_addressed(self) -> None:
        manifest = authorized_manifest()

        self.assertEqual(
            LiveExecutionAuthorizationManifest.from_dict(manifest.as_dict()),
            manifest,
        )
        drifted = manifest.as_dict()
        drifted["turn_id"] = "another-turn"
        with self.assertRaisesRegex(
            ValueError,
            "authorization manifest content hash mismatch",
        ):
            LiveExecutionAuthorizationManifest.from_dict(drifted)

    def test_authorization_must_match_current_turn_time_and_exact_interactions(
        self,
    ) -> None:
        cases = (
            (
                authorized_manifest(turn_id="old-turn"),
                "authorization_not_current_turn",
            ),
            (
                authorized_manifest(
                    issued_at=NOW - timedelta(minutes=20),
                    expires_at=NOW,
                ),
                "authorization_expired",
            ),
            (
                authorized_manifest(
                    issued_at=NOW + timedelta(minutes=1),
                    expires_at=NOW + timedelta(minutes=20),
                ),
                "authorization_not_yet_valid",
            ),
            (
                authorized_manifest(
                    interactions=(
                        "live_primary_sources",
                        "licensed_market_data",
                        "model_provider",
                    )
                ),
                "database_interaction_not_authorized",
            ),
            (
                authorized_manifest(
                    interactions=(
                        "hosted_database",
                        "live_primary_sources",
                        "model_provider",
                    )
                ),
                "market_interaction_not_authorized",
            ),
            (
                authorized_manifest(
                    interactions=(
                        "hosted_database",
                        "live_primary_sources",
                        "licensed_market_data",
                    )
                ),
                "model_interaction_not_authorized",
            ),
        )

        for manifest, reason in cases:
            with self.subTest(reason=reason):
                decision = evaluate_live_mvp_preflight(
                    manifest=manifest,
                    inputs=passing_inputs(),
                )
                self.assertFalse(decision.allowed)
                self.assertIn(reason, decision.blocking_reason_codes)
                self.assertEqual(decision.permitted_interactions, ())

    def test_authorization_must_match_current_operator(self) -> None:
        decision = evaluate_live_mvp_preflight(
            manifest=authorized_manifest(),
            inputs=replace(
                passing_inputs(),
                current_operator_id="another-operator",
            ),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.blocking_reason_codes,
            ("authorization_operator_mismatch",),
        )
        self.assertEqual(decision.permitted_interactions, ())

    def test_all_production_license_hosted_and_budget_gates_fail_closed(
        self,
    ) -> None:
        blocked = replace(
            passing_inputs(),
            production_config_active=False,
            paid_evaluation_roles=("grader:moonshot",),
            sample_memo_approved=False,
            licensed_official_close_rights=False,
            licensed_authenticated_display_rights=False,
            hosted_isolation_verified=False,
            estimated_run_cost_usd=Decimal("8.00"),
            run_budget_remaining_usd=Decimal("7.00"),
            daily_budget_remaining_usd=Decimal("5.00"),
            monthly_budget_remaining_usd=Decimal("4.00"),
        )

        decision = evaluate_live_mvp_preflight(
            manifest=authorized_manifest(),
            inputs=blocked,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.blocking_reason_codes,
            (
                "production_config_inactive",
                "paid_evaluations_incomplete",
                "sample_memo_not_approved",
                "licensed_official_close_rights_missing",
                "licensed_authenticated_display_rights_missing",
                "hosted_isolation_not_verified",
                "run_budget_unavailable",
                "daily_budget_unavailable",
                "monthly_budget_unavailable",
            ),
        )
        self.assertEqual(decision.permitted_interactions, ())

    def test_passing_preflight_returns_only_sanitized_interaction_permissions(
        self,
    ) -> None:
        manifest = authorized_manifest()

        decision = evaluate_live_mvp_preflight(
            manifest=manifest,
            inputs=passing_inputs(),
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.blocking_reason_codes, ())
        self.assertEqual(
            decision.permitted_interactions,
            (
                "hosted_database",
                "live_primary_sources",
                "licensed_market_data",
                "model_provider",
            ),
        )
        self.assertEqual(
            decision.authorization_manifest_sha256,
            manifest.content_sha256,
        )
        self.assertTrue(
            all(not callable(item) for item in decision.permitted_interactions)
        )

    def test_personal_research_requires_own_market_contract_not_licensed_rights(
        self,
    ) -> None:
        inputs = replace(
            passing_inputs(),
            thesis_contract_id=("biotech_moonshot_catalyst_personal_research_v1"),
            valuation_contract_version="valuation_snapshot.personal_research.v2",
            licensed_official_close_rights=False,
            licensed_authenticated_display_rights=False,
            personal_research_valuation_pipeline_verified=True,
            nasdaq_trader_live_contract_verified=True,
        )
        manifest = authorized_manifest(
            interactions=(
                "hosted_database",
                "live_primary_sources",
                "personal_market_data",
                "model_provider",
            )
        )

        decision = evaluate_live_mvp_preflight(
            manifest=manifest,
            inputs=inputs,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.blocking_reason_codes, ())
        self.assertEqual(
            decision.permitted_interactions,
            (
                "hosted_database",
                "live_primary_sources",
                "personal_market_data",
                "model_provider",
            ),
        )

    def test_personal_research_fails_closed_on_own_proof_or_contract_drift(
        self,
    ) -> None:
        inputs = replace(
            passing_inputs(),
            thesis_contract_id=("biotech_moonshot_catalyst_personal_research_v1"),
            valuation_contract_version="valuation_snapshot.v1",
            licensed_official_close_rights=True,
            licensed_authenticated_display_rights=True,
            personal_research_valuation_pipeline_verified=False,
            nasdaq_trader_live_contract_verified=False,
        )
        manifest = authorized_manifest(
            interactions=(
                "hosted_database",
                "live_primary_sources",
                "personal_market_data",
                "model_provider",
            )
        )

        decision = evaluate_live_mvp_preflight(
            manifest=manifest,
            inputs=inputs,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.blocking_reason_codes,
            (
                "personal_research_valuation_contract_mismatch",
                "personal_research_valuation_pipeline_unverified",
                "nasdaq_trader_live_contract_unverified",
            ),
        )
        self.assertEqual(decision.permitted_interactions, ())

    def test_two_security_proof_requires_distinct_securities_and_exact_fingerprint(
        self,
    ) -> None:
        matching = prove_two_security_shared_contract(
            first_security_id="security-rxrx",
            first_contract_fingerprint="a" * 64,
            second_security_id="security-second",
            second_contract_fingerprint="a" * 64,
        )
        mismatched = prove_two_security_shared_contract(
            first_security_id="security-rxrx",
            first_contract_fingerprint="a" * 64,
            second_security_id="security-second",
            second_contract_fingerprint="b" * 64,
        )

        self.assertTrue(matching.matches)
        self.assertEqual(matching.shared_contract_fingerprint, "a" * 64)
        self.assertEqual(matching.blocking_reason_codes, ())
        self.assertFalse(mismatched.matches)
        self.assertIsNone(mismatched.shared_contract_fingerprint)
        self.assertEqual(
            mismatched.blocking_reason_codes,
            ("two_security_contract_fingerprint_mismatch",),
        )

    def test_more_permissive_budget_limits_are_rejected(self) -> None:
        decision = evaluate_live_mvp_preflight(
            manifest=authorized_manifest(),
            inputs=replace(
                passing_inputs(),
                run_budget_limit_usd=Decimal("7.01"),
                daily_budget_limit_usd=Decimal("14.01"),
                monthly_budget_limit_usd=Decimal("30.01"),
            ),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.blocking_reason_codes,
            (
                "run_budget_limit_not_approved",
                "daily_budget_limit_not_approved",
                "monthly_budget_limit_not_approved",
            ),
        )
        self.assertEqual(decision.permitted_interactions, ())

    def test_negative_cost_limits_or_capacity_fail_closed(self) -> None:
        decision = evaluate_live_mvp_preflight(
            manifest=authorized_manifest(),
            inputs=replace(
                passing_inputs(),
                estimated_run_cost_usd=Decimal("-1"),
                run_budget_limit_usd=Decimal("-1"),
                daily_budget_remaining_usd=Decimal("-1"),
            ),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.blocking_reason_codes,
            (
                "estimated_run_cost_invalid",
                "run_budget_limit_invalid",
                "daily_budget_remaining_invalid",
            ),
        )
        self.assertEqual(decision.permitted_interactions, ())


if __name__ == "__main__":
    unittest.main()
