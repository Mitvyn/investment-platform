from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import re
from typing import Mapping

from investment_research_os.production_execution import (
    MVP_EVALUATION_EXECUTION_ROLES,
)


AUTHORIZATION_MANIFEST_CONTRACT = "LiveExecutionAuthorizationManifest.v2"
LIVE_INTERACTIONS = (
    "hosted_database",
    "live_primary_sources",
    "licensed_market_data",
    "personal_market_data",
    "model_provider",
)
STRICT_THESIS_CONTRACT_ID = "biotech_moonshot_catalyst_assessment"
PERSONAL_RESEARCH_THESIS_CONTRACT_ID = "biotech_moonshot_catalyst_personal_research_v1"
STRICT_VALUATION_CONTRACT_VERSION = "valuation_snapshot.v1"
PERSONAL_RESEARCH_VALUATION_CONTRACT_VERSION = "valuation_snapshot.personal_research.v1"
APPROVED_RUN_BUDGET_USD = Decimal("7.00")
APPROVED_DAILY_BUDGET_USD = Decimal("14.00")
APPROVED_MONTHLY_BUDGET_USD = Decimal("30.00")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _content_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _non_empty_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _aware_datetime(value: object, field: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"invalid {field}") from error
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"invalid {field}")
    return value


@dataclass(frozen=True, slots=True)
class LiveExecutionAuthorizationManifest:
    authorization_id: str
    operator_id: str
    turn_id: str
    issued_at: datetime
    expires_at: datetime
    authorized_interactions: tuple[str, ...]
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        authorization_id: str,
        operator_id: str,
        turn_id: str,
        issued_at: datetime,
        expires_at: datetime,
        authorized_interactions: tuple[str, ...],
    ) -> LiveExecutionAuthorizationManifest:
        content = cls._validated_content(
            {
                "contract_version": AUTHORIZATION_MANIFEST_CONTRACT,
                "authorization_id": authorization_id,
                "operator_id": operator_id,
                "turn_id": turn_id,
                "issued_at": issued_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "authorized_interactions": list(authorized_interactions),
            }
        )
        return cls._from_content(content, _content_sha256(content))

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
    ) -> LiveExecutionAuthorizationManifest:
        expected = {
            "contract_version",
            "authorization_id",
            "operator_id",
            "turn_id",
            "issued_at",
            "expires_at",
            "authorized_interactions",
            "content_sha256",
        }
        if set(value) != expected:
            raise ValueError("invalid authorization manifest fields")
        content = cls._validated_content(
            {key: value[key] for key in expected - {"content_sha256"}}
        )
        content_hash = _non_empty_text(value["content_sha256"], "content_sha256")
        if not _SHA256.fullmatch(content_hash):
            raise ValueError("invalid authorization manifest content hash")
        if _content_sha256(content) != content_hash:
            raise ValueError("authorization manifest content hash mismatch")
        return cls._from_content(content, content_hash)

    @staticmethod
    def _validated_content(value: Mapping[str, object]) -> dict[str, object]:
        if value.get("contract_version") != AUTHORIZATION_MANIFEST_CONTRACT:
            raise ValueError("unsupported authorization manifest contract")
        issued_at = _aware_datetime(value.get("issued_at"), "issued_at")
        expires_at = _aware_datetime(value.get("expires_at"), "expires_at")
        if expires_at <= issued_at:
            raise ValueError("authorization expiry must follow issue time")
        interactions = value.get("authorized_interactions")
        if not isinstance(interactions, (list, tuple)) or any(
            not isinstance(item, str) for item in interactions
        ):
            raise ValueError("invalid authorized interactions")
        if len(set(interactions)) != len(interactions) or any(
            item not in LIVE_INTERACTIONS for item in interactions
        ):
            raise ValueError("invalid authorized interactions")
        ordered = tuple(item for item in LIVE_INTERACTIONS if item in interactions)
        return {
            "contract_version": AUTHORIZATION_MANIFEST_CONTRACT,
            "authorization_id": _non_empty_text(
                value.get("authorization_id"), "authorization_id"
            ),
            "operator_id": _non_empty_text(value.get("operator_id"), "operator_id"),
            "turn_id": _non_empty_text(value.get("turn_id"), "turn_id"),
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "authorized_interactions": list(ordered),
        }

    @classmethod
    def _from_content(
        cls,
        content: Mapping[str, object],
        content_hash: str,
    ) -> LiveExecutionAuthorizationManifest:
        return cls(
            authorization_id=str(content["authorization_id"]),
            operator_id=str(content["operator_id"]),
            turn_id=str(content["turn_id"]),
            issued_at=datetime.fromisoformat(str(content["issued_at"])),
            expires_at=datetime.fromisoformat(str(content["expires_at"])),
            authorized_interactions=tuple(content["authorized_interactions"]),
            content_sha256=content_hash,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": AUTHORIZATION_MANIFEST_CONTRACT,
            "authorization_id": self.authorization_id,
            "operator_id": self.operator_id,
            "turn_id": self.turn_id,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "authorized_interactions": list(self.authorized_interactions),
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class LiveMvpPreflightInputs:
    current_operator_id: str
    current_turn_id: str
    checked_at: datetime
    production_config_active: bool
    paid_evaluation_roles: tuple[str, ...]
    sample_memo_approved: bool
    licensed_official_close_rights: bool
    licensed_authenticated_display_rights: bool
    hosted_isolation_verified: bool
    estimated_run_cost_usd: Decimal
    run_budget_limit_usd: Decimal
    daily_budget_limit_usd: Decimal
    monthly_budget_limit_usd: Decimal
    run_budget_remaining_usd: Decimal
    daily_budget_remaining_usd: Decimal
    monthly_budget_remaining_usd: Decimal
    thesis_contract_id: str = STRICT_THESIS_CONTRACT_ID
    valuation_contract_version: str = STRICT_VALUATION_CONTRACT_VERSION
    personal_research_valuation_pipeline_verified: bool = False
    nasdaq_trader_live_contract_verified: bool = False


@dataclass(frozen=True, slots=True)
class LiveMvpPreflightDecision:
    allowed: bool
    blocking_reason_codes: tuple[str, ...]
    permitted_interactions: tuple[str, ...]
    authorization_manifest_sha256: str | None


@dataclass(frozen=True, slots=True)
class TwoSecurityContractProof:
    matches: bool
    shared_contract_fingerprint: str | None
    blocking_reason_codes: tuple[str, ...]


def prove_two_security_shared_contract(
    *,
    first_security_id: str,
    first_contract_fingerprint: str,
    second_security_id: str,
    second_contract_fingerprint: str,
) -> TwoSecurityContractProof:
    reasons: list[str] = []
    if not first_security_id.strip() or not second_security_id.strip():
        reasons.append("acceptance_security_id_invalid")
    elif first_security_id == second_security_id:
        reasons.append("acceptance_securities_not_distinct")
    if not _SHA256.fullmatch(first_contract_fingerprint) or not _SHA256.fullmatch(
        second_contract_fingerprint
    ):
        reasons.append("contract_fingerprint_invalid")
    elif first_contract_fingerprint != second_contract_fingerprint:
        reasons.append("two_security_contract_fingerprint_mismatch")
    return TwoSecurityContractProof(
        matches=not reasons,
        shared_contract_fingerprint=(
            first_contract_fingerprint if not reasons else None
        ),
        blocking_reason_codes=tuple(reasons),
    )


def evaluate_live_mvp_preflight(
    *,
    manifest: LiveExecutionAuthorizationManifest | None,
    inputs: LiveMvpPreflightInputs,
) -> LiveMvpPreflightDecision:
    if manifest is None:
        return LiveMvpPreflightDecision(
            allowed=False,
            blocking_reason_codes=("authorization_manifest_missing",),
            permitted_interactions=(),
            authorization_manifest_sha256=None,
        )
    reasons: list[str] = []
    if manifest.operator_id != inputs.current_operator_id:
        reasons.append("authorization_operator_mismatch")
    if manifest.turn_id != inputs.current_turn_id:
        reasons.append("authorization_not_current_turn")
    if inputs.checked_at < manifest.issued_at:
        reasons.append("authorization_not_yet_valid")
    if inputs.checked_at >= manifest.expires_at:
        reasons.append("authorization_expired")
    required_interactions = _required_interactions(inputs.thesis_contract_id)
    interaction_reasons = {
        "hosted_database": "database_interaction_not_authorized",
        "live_primary_sources": "primary_source_interaction_not_authorized",
        "licensed_market_data": "market_interaction_not_authorized",
        "personal_market_data": "personal_market_interaction_not_authorized",
        "model_provider": "model_interaction_not_authorized",
    }
    if required_interactions is None:
        reasons.append("thesis_contract_unsupported")
    else:
        reasons.extend(
            interaction_reasons[interaction]
            for interaction in required_interactions
            if interaction not in manifest.authorized_interactions
        )
        if manifest.authorized_interactions != required_interactions:
            reasons.append("authorization_interactions_not_exact")
    if reasons:
        return LiveMvpPreflightDecision(
            allowed=False,
            blocking_reason_codes=tuple(reasons),
            permitted_interactions=(),
            authorization_manifest_sha256=manifest.content_sha256,
        )
    if not inputs.production_config_active:
        reasons.append("production_config_inactive")
    if inputs.paid_evaluation_roles != MVP_EVALUATION_EXECUTION_ROLES:
        reasons.append("paid_evaluations_incomplete")
    if not inputs.sample_memo_approved:
        reasons.append("sample_memo_not_approved")
    if inputs.thesis_contract_id == STRICT_THESIS_CONTRACT_ID:
        if inputs.valuation_contract_version != STRICT_VALUATION_CONTRACT_VERSION:
            reasons.append("strict_valuation_contract_mismatch")
        if not inputs.licensed_official_close_rights:
            reasons.append("licensed_official_close_rights_missing")
        if not inputs.licensed_authenticated_display_rights:
            reasons.append("licensed_authenticated_display_rights_missing")
    elif inputs.thesis_contract_id == PERSONAL_RESEARCH_THESIS_CONTRACT_ID:
        if (
            inputs.valuation_contract_version
            != PERSONAL_RESEARCH_VALUATION_CONTRACT_VERSION
        ):
            reasons.append("personal_research_valuation_contract_mismatch")
        if not inputs.personal_research_valuation_pipeline_verified:
            reasons.append("personal_research_valuation_pipeline_unverified")
        if not inputs.nasdaq_trader_live_contract_verified:
            reasons.append("nasdaq_trader_live_contract_unverified")
    if not inputs.hosted_isolation_verified:
        reasons.append("hosted_isolation_not_verified")
    if inputs.estimated_run_cost_usd <= 0:
        reasons.append("estimated_run_cost_invalid")
    if inputs.run_budget_limit_usd <= 0:
        reasons.append("run_budget_limit_invalid")
    elif inputs.run_budget_limit_usd > APPROVED_RUN_BUDGET_USD:
        reasons.append("run_budget_limit_not_approved")
    if inputs.daily_budget_limit_usd <= 0:
        reasons.append("daily_budget_limit_invalid")
    elif inputs.daily_budget_limit_usd > APPROVED_DAILY_BUDGET_USD:
        reasons.append("daily_budget_limit_not_approved")
    if inputs.monthly_budget_limit_usd <= 0:
        reasons.append("monthly_budget_limit_invalid")
    elif inputs.monthly_budget_limit_usd > APPROVED_MONTHLY_BUDGET_USD:
        reasons.append("monthly_budget_limit_not_approved")
    if inputs.run_budget_remaining_usd < 0:
        reasons.append("run_budget_remaining_invalid")
    if inputs.daily_budget_remaining_usd < 0:
        reasons.append("daily_budget_remaining_invalid")
    if inputs.monthly_budget_remaining_usd < 0:
        reasons.append("monthly_budget_remaining_invalid")
    if inputs.estimated_run_cost_usd > 0 and (
        inputs.run_budget_remaining_usd >= 0
        and inputs.estimated_run_cost_usd > inputs.run_budget_remaining_usd
    ):
        reasons.append("run_budget_unavailable")
    if inputs.estimated_run_cost_usd > 0 and (
        inputs.daily_budget_remaining_usd >= 0
        and inputs.estimated_run_cost_usd > inputs.daily_budget_remaining_usd
    ):
        reasons.append("daily_budget_unavailable")
    if inputs.estimated_run_cost_usd > 0 and (
        inputs.monthly_budget_remaining_usd >= 0
        and inputs.estimated_run_cost_usd > inputs.monthly_budget_remaining_usd
    ):
        reasons.append("monthly_budget_unavailable")
    return LiveMvpPreflightDecision(
        allowed=not reasons,
        blocking_reason_codes=tuple(reasons),
        permitted_interactions=required_interactions if not reasons else (),
        authorization_manifest_sha256=manifest.content_sha256,
    )


def _required_interactions(thesis_contract_id: str) -> tuple[str, ...] | None:
    if thesis_contract_id == STRICT_THESIS_CONTRACT_ID:
        return (
            "hosted_database",
            "live_primary_sources",
            "licensed_market_data",
            "model_provider",
        )
    if thesis_contract_id == PERSONAL_RESEARCH_THESIS_CONTRACT_ID:
        return (
            "hosted_database",
            "live_primary_sources",
            "personal_market_data",
            "model_provider",
        )
    return None


__all__ = [
    "APPROVED_DAILY_BUDGET_USD",
    "APPROVED_MONTHLY_BUDGET_USD",
    "APPROVED_RUN_BUDGET_USD",
    "AUTHORIZATION_MANIFEST_CONTRACT",
    "LIVE_INTERACTIONS",
    "LiveExecutionAuthorizationManifest",
    "LiveMvpPreflightDecision",
    "LiveMvpPreflightInputs",
    "TwoSecurityContractProof",
    "evaluate_live_mvp_preflight",
    "prove_two_security_shared_contract",
]
