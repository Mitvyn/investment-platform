from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import unittest

from investment_research_os.hosted_verification import (
    HostedVerificationAuthorization,
    HostedVerificationPlan,
    HostedVerificationProbe,
)
from investment_research_os.hosted_negative_probe import (
    HostedNegativeProbeError,
    HostedNegativeProbeRequest,
    SupabaseHostedNegativeProbePort,
)
from investment_research_os.hosted_verification_v3 import (
    HostedProbeDispatch,
    HostedProbeFixture,
    HostedVerificationExecutionAuthorization,
    HostedVerificationExecutionContract,
)
from workers.sec.storage import JsonResponse, SupabaseStorageSettings


OPERATOR_ID = "11111111-1111-4111-8111-111111111111"
TARGET_ID = "22222222-2222-4222-8222-222222222222"
AUTHORIZATION_SHA256 = "a" * 64
EXPECTED_CONSTRAINT = "iros_research_runs_contract_immutable"
NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


class RecordingTransport:
    def __init__(self, response: JsonResponse) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def request_json(self, method, url, *, headers, payload=None):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "payload": dict(payload or {}),
            }
        )
        return self.response


class HostedNegativeProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        plan = HostedVerificationPlan.freeze(
            probes=(
                HostedVerificationProbe(
                    probe_id="immutable.research_run",
                    category="immutable_constraint",
                    required_scope="negative_constraint_probe",
                    expected_result_code="mutation_rejected",
                    expected_count=1,
                ),
            ),
            target_objects=("iros_research_runs",),
        )
        fixture = HostedProbeFixture.freeze(
            fixture_id="fixture.immutable_research_run",
            setup_state="finalized_row",
            row_identity="immutable_research_run_row",
            target_owner_role="owner",
            cleanup_rule="transaction_rollback",
        )
        dispatch = HostedProbeDispatch.freeze(
            probe_id="immutable.research_run",
            transport_owner="database",
            operation="attempt_update",
            target_objects=("iros_research_runs",),
            subject_role="audit_permitted",
            fixture_id=fixture.fixture_id,
            mutation_field="idempotency_key",
            privileged_rpc="iros_run_hosted_negative_probe",
            expected_constraint=EXPECTED_CONSTRAINT,
            rollback_assertion="required_and_verified",
        )
        cls.contract = HostedVerificationExecutionContract.freeze(
            plan=plan,
            dispatches=(dispatch,),
            fixtures=(fixture,),
            inventory_sha256="1" * 64,
            constraint_index_sha256="2" * 64,
        )

    def test_executes_exact_service_only_rpc_and_maps_verified_rejection(self) -> None:
        transport = RecordingTransport(
            JsonResponse(
                payload={
                    "contract_version": "hosted-negative-probe-result.v1",
                    "probe_id": "immutable.research_run",
                    "passed": True,
                    "result_code": "mutation_rejected",
                    "expected_constraint": EXPECTED_CONSTRAINT,
                    "observed_constraint": EXPECTED_CONSTRAINT,
                    "sqlstate": "P0001",
                    "rollback_verified": True,
                    "authorization_sha256": self.authorization.content_sha256,
                    "operator_id": OPERATOR_ID,
                    "target_id": TARGET_ID,
                    "fixture_state": "finalized_row",
                    "request_sha256": self.request.content_sha256,
                },
                status=200,
                headers={},
            )
        )
        port = SupabaseHostedNegativeProbePort(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
            clock=lambda: NOW,
        )
        outcome = self._execute(port)

        self.assertTrue(outcome.passed)
        self.assertEqual(outcome.result_code, "mutation_rejected")
        self.assertEqual(outcome.observed_constraint, EXPECTED_CONSTRAINT)
        self.assertTrue(outcome.rollback_verified)
        self.assertIsNotNone(outcome.artifact_sha256)
        self.assertEqual(
            transport.requests,
            [
                {
                    "method": "POST",
                    "url": (
                        "https://example.supabase.co/rest/v1/rpc/"
                        "iros_run_hosted_negative_probe"
                    ),
                    "headers": {
                        "Content-Type": "application/json",
                        "apikey": "sb_secret_test",
                    },
                    "payload": {
                        "p_probe_id": "immutable.research_run",
                        "p_operator_id": OPERATOR_ID,
                        "p_target_id": TARGET_ID,
                        "p_authorization_sha256": self.authorization.content_sha256,
                        "p_fixture_state": "finalized_row",
                        "p_request_sha256": self.request.content_sha256,
                    },
                }
            ],
        )

    def test_preserves_verified_rollback_when_mutation_unexpectedly_succeeds(
        self,
    ) -> None:
        transport = RecordingTransport(
            JsonResponse(
                payload={
                    "contract_version": "hosted-negative-probe-result.v1",
                    "probe_id": "immutable.research_run",
                    "passed": False,
                    "result_code": "mutation_unexpectedly_succeeded",
                    "expected_constraint": EXPECTED_CONSTRAINT,
                    "observed_constraint": None,
                    "sqlstate": "P9001",
                    "rollback_verified": True,
                    "authorization_sha256": self.authorization.content_sha256,
                    "operator_id": OPERATOR_ID,
                    "target_id": TARGET_ID,
                    "fixture_state": "finalized_row",
                    "request_sha256": self.request.content_sha256,
                },
                status=200,
                headers={},
            )
        )
        port = SupabaseHostedNegativeProbePort(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
            clock=lambda: NOW,
        )

        outcome = self._execute(port)

        self.assertFalse(outcome.passed)
        self.assertEqual(outcome.result_code, "mutation_unexpectedly_succeeded")
        self.assertIsNone(outcome.observed_constraint)
        self.assertTrue(outcome.rollback_verified)

    def test_preserves_unproven_rollback_as_failed_audit_outcome(self) -> None:
        transport = RecordingTransport(
            JsonResponse(
                payload={
                    "contract_version": "hosted-negative-probe-result.v1",
                    "probe_id": "immutable.research_run",
                    "passed": False,
                    "result_code": "rollback_unproven",
                    "expected_constraint": EXPECTED_CONSTRAINT,
                    "observed_constraint": EXPECTED_CONSTRAINT,
                    "sqlstate": "P0001",
                    "rollback_verified": False,
                    "authorization_sha256": self.authorization.content_sha256,
                    "operator_id": OPERATOR_ID,
                    "target_id": TARGET_ID,
                    "fixture_state": "finalized_row",
                    "request_sha256": self.request.content_sha256,
                },
                status=200,
                headers={},
            )
        )
        port = SupabaseHostedNegativeProbePort(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
            clock=lambda: NOW,
        )

        outcome = self._execute(port)

        self.assertFalse(outcome.passed)
        self.assertEqual(outcome.result_code, "rollback_unproven")
        self.assertEqual(outcome.observed_constraint, EXPECTED_CONSTRAINT)
        self.assertFalse(outcome.rollback_verified)

    def test_rejects_result_from_different_authorization(self) -> None:
        transport = RecordingTransport(
            JsonResponse(
                payload={
                    "contract_version": "hosted-negative-probe-result.v1",
                    "probe_id": "immutable.research_run",
                    "passed": True,
                    "result_code": "mutation_rejected",
                    "expected_constraint": EXPECTED_CONSTRAINT,
                    "observed_constraint": EXPECTED_CONSTRAINT,
                    "sqlstate": "P0001",
                    "rollback_verified": True,
                    "authorization_sha256": "b" * 64,
                    "operator_id": OPERATOR_ID,
                    "target_id": TARGET_ID,
                    "fixture_state": "finalized_row",
                    "request_sha256": self.request.content_sha256,
                },
                status=200,
                headers={},
            )
        )
        port = SupabaseHostedNegativeProbePort(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
            clock=lambda: NOW,
        )

        with self.assertRaisesRegex(
            HostedNegativeProbeError,
            "result contract mismatch",
        ):
            self._execute(port)

    def test_rejects_result_from_different_target(self) -> None:
        payload = self._passed_payload()
        payload["target_id"] = "33333333-3333-4333-8333-333333333333"
        port = self._port(payload)

        with self.assertRaisesRegex(
            HostedNegativeProbeError,
            "result contract mismatch",
        ):
            self._execute(port)

    def test_rejects_tampered_request_before_transport(self) -> None:
        transport = RecordingTransport(
            JsonResponse(payload=None, status=500, headers={})
        )
        port = SupabaseHostedNegativeProbePort(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
            clock=lambda: NOW,
        )
        request = replace(
            self.request,
            target_id="33333333-3333-4333-8333-333333333333",
        )

        with self.assertRaisesRegex(
            HostedNegativeProbeError,
            "request contract is invalid",
        ):
            self._execute(port, request=request)

        self.assertEqual(transport.requests, [])

    def test_rejects_operator_not_bound_to_authorized_owner(self) -> None:
        authorization = HostedVerificationAuthorization.freeze(
            authorization_id=self.authorization.authorization_id,
            issue_id=self.authorization.issue_id,
            database_scope=self.authorization.database_scope,
            operator_id=self.authorization.operator_id,
            owner_subject_id="55555555-5555-4555-8555-555555555555",
            unrelated_subject_id=self.authorization.unrelated_subject_id,
            audit_subject_id=self.authorization.audit_subject_id,
            turn_id=self.authorization.turn_id,
            issued_at=self.authorization.issued_at,
            expires_at=self.authorization.expires_at,
            authorized_scopes=self.authorization.authorized_scopes,
        )

        with self.assertRaisesRegex(
            ValueError,
            "operator binding is invalid",
        ):
            HostedNegativeProbeRequest.freeze(
                execution_contract=self.contract,
                authorization=authorization,
                execution_authorization=HostedVerificationExecutionAuthorization.freeze(
                    authorization=authorization,
                    execution_contract=self.contract,
                ),
                target_id=TARGET_ID,
                current_turn_id=self.authorization.turn_id,
                checked_at=NOW,
            )

    def test_rejects_expired_authorization_before_transport(self) -> None:
        execution_authorization = HostedVerificationExecutionAuthorization.freeze(
            authorization=self.authorization,
            execution_contract=self.contract,
        )

        with self.assertRaisesRegex(ValueError, "authorization is not current"):
            HostedNegativeProbeRequest.freeze(
                execution_contract=self.contract,
                authorization=self.authorization,
                execution_authorization=execution_authorization,
                target_id=TARGET_ID,
                current_turn_id=self.authorization.turn_id,
                checked_at=self.authorization.expires_at,
            )

    def test_rechecks_expiry_immediately_before_transport(self) -> None:
        transport = RecordingTransport(
            JsonResponse(payload=self._passed_payload(), status=200, headers={})
        )
        port = SupabaseHostedNegativeProbePort(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
            clock=lambda: self.authorization.expires_at,
        )

        with self.assertRaisesRegex(
            HostedNegativeProbeError,
            "authorization is not current",
        ):
            self._execute(port)

        self.assertEqual(transport.requests, [])

    def setUp(self) -> None:
        self.authorization = HostedVerificationAuthorization.freeze(
            authorization_id="authorization-iro-052-negative-probe",
            issue_id="IRO-052",
            database_scope="iros_only",
            operator_id=OPERATOR_ID,
            owner_subject_id=OPERATOR_ID,
            unrelated_subject_id="33333333-3333-4333-8333-333333333333",
            audit_subject_id="44444444-4444-4444-8444-444444444444",
            turn_id="turn-iro-052-negative-probe",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=15),
            authorized_scopes=self.contract.required_scopes,
        )
        self.execution_authorization = HostedVerificationExecutionAuthorization.freeze(
            authorization=self.authorization,
            execution_contract=self.contract,
        )
        self.request = HostedNegativeProbeRequest.freeze(
            execution_contract=self.contract,
            authorization=self.authorization,
            execution_authorization=self.execution_authorization,
            target_id=TARGET_ID,
            current_turn_id=self.authorization.turn_id,
            checked_at=NOW,
        )

    def _passed_payload(self) -> dict[str, object]:
        return {
            "contract_version": "hosted-negative-probe-result.v1",
            "probe_id": "immutable.research_run",
            "passed": True,
            "result_code": "mutation_rejected",
            "expected_constraint": EXPECTED_CONSTRAINT,
            "observed_constraint": EXPECTED_CONSTRAINT,
            "sqlstate": "P0001",
            "rollback_verified": True,
            "authorization_sha256": self.authorization.content_sha256,
            "operator_id": OPERATOR_ID,
            "target_id": TARGET_ID,
            "fixture_state": "finalized_row",
            "request_sha256": self.request.content_sha256,
        }

    def _execute(
        self,
        port: SupabaseHostedNegativeProbePort,
        *,
        request: HostedNegativeProbeRequest | None = None,
    ):
        return port.execute(
            request or self.request,
            execution_contract=self.contract,
            authorization=self.authorization,
            execution_authorization=self.execution_authorization,
            current_turn_id=self.authorization.turn_id,
        )

    @staticmethod
    def _port(payload: dict[str, object]) -> SupabaseHostedNegativeProbePort:
        return SupabaseHostedNegativeProbePort(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=RecordingTransport(
                JsonResponse(payload=payload, status=200, headers={})
            ),
            clock=lambda: NOW,
        )


if __name__ == "__main__":
    unittest.main()
