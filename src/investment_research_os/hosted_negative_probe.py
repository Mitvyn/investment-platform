from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Callable, Mapping
from urllib.parse import urlsplit
from uuid import UUID

from investment_research_os.hosted_verification import HostedVerificationAuthorization
from investment_research_os.hosted_verification_v3 import (
    HostedVerificationExecutionAuthorization,
    HostedVerificationExecutionContract,
)
from investment_research_os.hosted_verification_v3_record import HostedProbeOutcome
from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)


_PROBE_ID = "immutable.research_run"
_EXPECTED_CONSTRAINT = "iros_research_runs_contract_immutable"
_RESULT_FIELDS = frozenset(
    {
        "contract_version",
        "probe_id",
        "passed",
        "result_code",
        "expected_constraint",
        "observed_constraint",
        "sqlstate",
        "rollback_verified",
        "authorization_sha256",
        "operator_id",
        "target_id",
        "fixture_state",
        "request_sha256",
    }
)


class HostedNegativeProbeError(RuntimeError):
    """Raised when a hosted negative-probe result is not trustworthy."""


def _canonical_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError("hosted negative probe UUID is invalid") from error
    if str(parsed) != value:
        raise ValueError("hosted negative probe UUID is noncanonical")
    return value


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class HostedNegativeProbeRequest:
    probe_id: str
    operator_id: str
    target_id: str
    authorization_sha256: str
    execution_authorization_sha256: str
    fixture_state: str
    expected_constraint: str
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        execution_contract: HostedVerificationExecutionContract,
        authorization: HostedVerificationAuthorization,
        execution_authorization: HostedVerificationExecutionAuthorization,
        target_id: str,
        current_turn_id: str,
        checked_at: datetime,
    ) -> HostedNegativeProbeRequest:
        authorization.assert_valid_contract()
        if (
            not authorization.has_valid_content_hash()
            or not execution_contract.has_valid_content_hash()
            or not execution_authorization.has_valid_content_hash()
            or execution_authorization.authorization_sha256
            != authorization.content_sha256
            or execution_authorization.execution_contract_sha256
            != execution_contract.content_sha256
        ):
            raise ValueError("hosted negative probe authorization binding is invalid")
        if (
            authorization.operator_id != authorization.owner_subject_id
            or _canonical_uuid(authorization.operator_id) != authorization.operator_id
        ):
            raise ValueError("hosted negative probe operator binding is invalid")
        if (
            checked_at.tzinfo is None
            or checked_at.utcoffset() is None
            or checked_at < authorization.issued_at
            or checked_at >= authorization.expires_at
            or current_turn_id != authorization.turn_id
        ):
            raise ValueError("hosted negative probe authorization is not current")
        dispatches = {
            dispatch.probe_id: dispatch for dispatch in execution_contract.dispatches
        }
        dispatch = dispatches.get(_PROBE_ID)
        fixtures = {
            fixture.fixture_id: fixture for fixture in execution_contract.fixtures
        }
        fixture = fixtures.get(dispatch.fixture_id) if dispatch is not None else None
        if (
            dispatch is None
            or fixture is None
            or dispatch.operation != "attempt_update"
            or dispatch.target_objects != ("iros_research_runs",)
            or dispatch.privileged_rpc != "iros_run_hosted_negative_probe"
            or dispatch.expected_constraint != _EXPECTED_CONSTRAINT
            or dispatch.mutation_field != "idempotency_key"
            or dispatch.subject_role != "audit_permitted"
            or dispatch.rollback_assertion != "required_and_verified"
            or fixture.setup_state != "finalized_row"
            or fixture.cleanup_rule != "transaction_rollback"
            or "negative_constraint_probe" not in authorization.authorized_scopes
        ):
            raise ValueError("hosted negative probe contract is unsupported")
        content = {
            "probe_id": dispatch.probe_id,
            "operator_id": authorization.operator_id,
            "target_id": _canonical_uuid(target_id),
            "authorization_sha256": authorization.content_sha256,
            "execution_authorization_sha256": execution_authorization.content_sha256,
            "fixture_state": fixture.setup_state,
            "expected_constraint": dispatch.expected_constraint,
        }
        return cls(**content, content_sha256=_sha256(content))

    def has_valid_content_hash(self) -> bool:
        try:
            return (
                self.probe_id == _PROBE_ID
                and self.expected_constraint == _EXPECTED_CONSTRAINT
                and self.fixture_state == "finalized_row"
                and _canonical_uuid(self.operator_id) == self.operator_id
                and _canonical_uuid(self.target_id) == self.target_id
                and len(self.authorization_sha256) == 64
                and len(self.execution_authorization_sha256) == 64
                and all(
                    character in "0123456789abcdef"
                    for character in (
                        self.authorization_sha256
                        + self.execution_authorization_sha256
                    )
                )
                and self.content_sha256
                == _sha256(
                    {
                        "probe_id": self.probe_id,
                        "operator_id": self.operator_id,
                        "target_id": self.target_id,
                        "authorization_sha256": self.authorization_sha256,
                        "execution_authorization_sha256": (
                            self.execution_authorization_sha256
                        ),
                        "fixture_state": self.fixture_state,
                        "expected_constraint": self.expected_constraint,
                    }
                )
            )
        except ValueError:
            return False


class SupabaseHostedNegativeProbePort:
    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        parsed = urlsplit(settings.url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise HostedNegativeProbeError(
                "hosted negative probe Supabase URL must use HTTPS"
            )
        if not settings.secret_key.strip():
            raise HostedNegativeProbeError(
                "hosted negative probe Supabase secret key is required"
            )
        self._settings = settings
        self._transport = transport or UrllibJsonTransport(settings.timeout_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self,
        request: HostedNegativeProbeRequest,
        *,
        execution_contract: HostedVerificationExecutionContract,
        authorization: HostedVerificationAuthorization,
        execution_authorization: HostedVerificationExecutionAuthorization,
        current_turn_id: str,
    ) -> HostedProbeOutcome:
        if (
            not isinstance(request, HostedNegativeProbeRequest)
            or not request.has_valid_content_hash()
        ):
            raise HostedNegativeProbeError(
                "hosted negative probe request contract is invalid"
            )
        try:
            current_request = HostedNegativeProbeRequest.freeze(
                execution_contract=execution_contract,
                authorization=authorization,
                execution_authorization=execution_authorization,
                target_id=request.target_id,
                current_turn_id=current_turn_id,
                checked_at=self._clock(),
            )
        except ValueError as error:
            raise HostedNegativeProbeError(
                "hosted negative probe authorization is not current"
            ) from error
        if current_request.content_sha256 != request.content_sha256:
            raise HostedNegativeProbeError(
                "hosted negative probe request authorization mismatch"
            )
        try:
            response = self._transport.request_json(
                "POST",
                (
                    f"{self._settings.url.rstrip('/')}/rest/v1/rpc/"
                    "iros_run_hosted_negative_probe"
                ),
                headers={
                    "Content-Type": "application/json",
                    "apikey": self._settings.secret_key,
                },
                payload={
                    "p_probe_id": request.probe_id,
                    "p_operator_id": request.operator_id,
                    "p_target_id": request.target_id,
                    "p_authorization_sha256": request.authorization_sha256,
                    "p_fixture_state": request.fixture_state,
                    "p_request_sha256": request.content_sha256,
                },
            )
        except EvidenceStorageError as error:
            raise HostedNegativeProbeError(
                "hosted negative probe transport failed"
            ) from error
        if not 200 <= response.status < 300:
            raise HostedNegativeProbeError(
                f"hosted negative probe returned HTTP {response.status}"
            )
        result = _result_mapping(response.payload)
        if (
            result["contract_version"] != "hosted-negative-probe-result.v1"
            or result["probe_id"] != request.probe_id
            or result["authorization_sha256"] != request.authorization_sha256
            or result["operator_id"] != request.operator_id
            or result["target_id"] != request.target_id
            or result["fixture_state"] != request.fixture_state
            or result["request_sha256"] != request.content_sha256
            or result["expected_constraint"] != request.expected_constraint
        ):
            raise HostedNegativeProbeError(
                "hosted negative probe result contract mismatch"
            )
        passed = result["passed"]
        result_code = result["result_code"]
        observed_constraint = result["observed_constraint"]
        sqlstate = result["sqlstate"]
        rollback_verified = result["rollback_verified"]
        if type(passed) is not bool or type(rollback_verified) is not bool:
            raise HostedNegativeProbeError("hosted negative probe result is invalid")
        if passed:
            valid_result = (
                result_code == "mutation_rejected"
                and observed_constraint == request.expected_constraint
                and sqlstate == "P0001"
                and rollback_verified
            )
        else:
            valid_sqlstate = isinstance(sqlstate, str) and len(sqlstate) == 5
            if result_code == "mutation_unexpectedly_succeeded":
                valid_result = (
                    observed_constraint is None
                    and sqlstate == "P9001"
                    and rollback_verified
                )
            elif result_code == "unexpected_database_error":
                valid_result = (
                    observed_constraint is None and valid_sqlstate and rollback_verified
                )
            elif result_code == "rollback_unproven":
                valid_result = (
                    observed_constraint in {None, request.expected_constraint}
                    and valid_sqlstate
                    and not rollback_verified
                )
            else:
                valid_result = False
        if not valid_result:
            raise HostedNegativeProbeError("hosted negative probe result is invalid")
        return HostedProbeOutcome.freeze(
            probe_id=request.probe_id,
            passed=passed,
            result_code=str(result_code),
            count=1,
            observed_constraint=(
                str(observed_constraint) if observed_constraint is not None else None
            ),
            rollback_verified=rollback_verified,
            artifact_sha256=_sha256(result),
        )


def _result_mapping(payload: object) -> Mapping[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != _RESULT_FIELDS:
        raise HostedNegativeProbeError("hosted negative probe response is malformed")
    return payload


__all__ = [
    "HostedNegativeProbeError",
    "HostedNegativeProbeRequest",
    "SupabaseHostedNegativeProbePort",
]
