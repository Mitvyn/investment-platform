from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping
from urllib.parse import urlencode

from investment_research_os.ids import stable_id
from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)

from . import (
    CapitalStructureInput,
    CorporateActionReconciliation,
    DerivedValuation,
    DilutionInstrument,
    MarketSession,
    MaterialityAssessment,
    PriceObservation,
    ValuationAssurance,
    ValuationSnapshot,
    ValuationSourceReference,
)


class SupabaseValuationSnapshotRepository:
    """Persists one immutable, owner-scoped snapshot per research run."""

    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def save(self, snapshot: ValuationSnapshot) -> ValuationSnapshot:
        existing = self.get_for_run(snapshot.operator_id, snapshot.research_run_id)
        if existing is not None:
            return self._require_exact_match(existing, snapshot)

        for table, conflict_columns, record in self._records(snapshot):
            self._insert(table, conflict_columns, record)
        self._finalize(snapshot)
        persisted = self.get_for_run(snapshot.operator_id, snapshot.research_run_id)
        if persisted is None:
            raise EvidenceStorageError("persisted valuation snapshot is unavailable")
        return self._require_exact_match(persisted, snapshot)

    def get(
        self,
        operator_id: str,
        snapshot_id: str,
    ) -> ValuationSnapshot | None:
        return self._get_one(
            {
                "operator_id": f"eq.{operator_id}",
                "valuation_snapshot_id": f"eq.{snapshot_id}",
            }
        )

    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> ValuationSnapshot | None:
        return self._get_one(
            {
                "operator_id": f"eq.{operator_id}",
                "research_run_id": f"eq.{research_run_id}",
            }
        )

    def _get_one(self, filters: Mapping[str, str]) -> ValuationSnapshot | None:
        query = urlencode({**filters, "select": "canonical_snapshot"})
        response = self.transport.request_json(
            "GET",
            (
                f"{self.settings.url.rstrip('/')}/rest/v1/"
                f"iros_v_research_run_valuation_snapshot?{query}"
            ),
            headers={"apikey": self.settings.secret_key},
        )
        if response.status != 200:
            raise EvidenceStorageError(
                "valuation snapshot store returned "
                f"HTTP {response.status} for composed snapshot view"
            )
        if not isinstance(response.payload, list):
            raise EvidenceStorageError(
                "valuation snapshot view returned invalid payload"
            )
        if not response.payload:
            return None
        if len(response.payload) != 1 or not isinstance(response.payload[0], dict):
            raise EvidenceStorageError(
                "valuation snapshot view returned duplicate rows"
            )
        payload = response.payload[0].get("canonical_snapshot")
        if not isinstance(payload, dict):
            raise EvidenceStorageError(
                "valuation snapshot view returned invalid contract"
            )
        try:
            snapshot = _snapshot_from_wire(payload)
        except (KeyError, TypeError, ValueError) as error:
            raise EvidenceStorageError(
                "valuation snapshot view returned invalid contract"
            ) from error
        if snapshot.as_dict() != payload:
            raise EvidenceStorageError(
                "valuation snapshot view returned non-canonical contract"
            )
        return snapshot

    def _insert(
        self,
        table: str,
        conflict_columns: str,
        record: Mapping[str, Any],
    ) -> None:
        query = urlencode({"on_conflict": conflict_columns})
        response = self.transport.request_json(
            "POST",
            f"{self.settings.url.rstrip('/')}/rest/v1/{table}?{query}",
            headers={
                "Content-Type": "application/json",
                "Prefer": "resolution=ignore-duplicates,return=minimal",
                "apikey": self.settings.secret_key,
            },
            payload=record,
        )
        if response.status not in (200, 201, 204):
            raise EvidenceStorageError(
                f"valuation snapshot store returned HTTP {response.status} for {table}"
            )

    def _finalize(self, snapshot: ValuationSnapshot) -> None:
        query = urlencode(
            {
                "id": f"eq.{snapshot.id}",
                "operator_id": f"eq.{snapshot.operator_id}",
                "persistence_state": "eq.draft",
            }
        )
        response = self.transport.request_json(
            "PATCH",
            (
                f"{self.settings.url.rstrip('/')}/rest/v1/"
                f"iros_valuation_snapshots?{query}"
            ),
            headers={
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
                "apikey": self.settings.secret_key,
            },
            payload={"persistence_state": "complete"},
        )
        if response.status not in (200, 204):
            raise EvidenceStorageError(
                "valuation snapshot store returned "
                f"HTTP {response.status} while finalizing iros_valuation_snapshots"
            )

    @staticmethod
    def _require_exact_match(
        persisted: ValuationSnapshot,
        requested: ValuationSnapshot,
    ) -> ValuationSnapshot:
        if persisted.as_dict() != requested.as_dict():
            raise EvidenceStorageError(
                "persisted valuation snapshot does not match requested contract"
            )
        return persisted

    @staticmethod
    def _records(
        snapshot: ValuationSnapshot,
    ) -> list[tuple[str, str, Mapping[str, Any]]]:
        wire = snapshot.as_dict()
        price = _optional_mapping(wire["price_basis"])
        corporate_action = _mapping(wire["corporate_action_reconciliation"])
        basic = _optional_mapping(wire["basic_shares_outstanding"])
        diluted = _optional_mapping(wire["fully_diluted_shares"])
        cash = _optional_mapping(wire["cash"])
        debt = _optional_mapping(wire["debt"])
        market_cap = _optional_mapping(wire["market_capitalization"])
        enterprise_value = _optional_mapping(wire["enterprise_value"])
        records: list[tuple[str, str, Mapping[str, Any]]] = [
            (
                "iros_valuation_snapshots",
                "operator_id,research_run_id",
                {
                    "id": snapshot.id,
                    "operator_id": snapshot.operator_id,
                    "research_run_id": snapshot.research_run_id,
                    "evidence_bundle_id": snapshot.evidence_bundle_id,
                    "evidence_bundle_hash": snapshot.evidence_bundle_hash,
                    "security_id": snapshot.security_id,
                    "as_of_cutoff": wire["as_of_cutoff"],
                    "snapshot_status": snapshot.snapshot_status,
                    "invalid_reason_codes": list(snapshot.invalid_reason_codes),
                    "currency": wire["currency"],
                    "price_type": price.get("price_type") if price else None,
                    "session_type": price.get("session_type") if price else None,
                    "session_date": price.get("session_date") if price else None,
                    "primary_listing_exchange": (
                        price.get("primary_listing_exchange") if price else None
                    ),
                    "share_price": price.get("share_price") if price else None,
                    "official_close_timestamp": (
                        (
                            price.get("official_close_timestamp")
                            or price.get("price_timestamp")
                        )
                        if price
                        else None
                    ),
                    "price_timestamp": (
                        price.get("price_timestamp") if price else None
                    ),
                    "halt_verification_status": (
                        price.get("halt_verification_status") if price else None
                    ),
                    "market_calendar_version": (
                        price.get("market_calendar_version") if price else None
                    ),
                    "market_status": price.get("market_status") if price else None,
                    "corporate_action_adjustment_status": corporate_action[
                        "price_adjustment_status"
                    ],
                    "provider_source_reference_id": (
                        price.get("provider_source_reference_id") if price else None
                    ),
                    "basic_shares_outstanding": (basic.get("value") if basic else None),
                    "fully_diluted_shares": (diluted.get("value") if diluted else None),
                    "cash": cash.get("value") if cash else None,
                    "debt": debt.get("value") if debt else None,
                    "market_capitalization": (
                        market_cap.get("value") if market_cap else None
                    ),
                    "enterprise_value": (
                        enterprise_value.get("value") if enterprise_value else None
                    ),
                    "corporate_action_event_id": corporate_action["event_id"],
                    "corporate_action_event_type": corporate_action["event_type"],
                    "corporate_action_effective_at": corporate_action["effective_at"],
                    "share_count_adjustment_status": corporate_action[
                        "share_count_adjustment_status"
                    ],
                    "corporate_action_reconciliation_result": corporate_action[
                        "reconciliation_result"
                    ],
                    "corporate_action_reconciliation": corporate_action,
                    "price_information_state": snapshot.price_information_state,
                    "market_relative_analysis_permitted": (
                        snapshot.market_relative_analysis_permitted
                    ),
                    "price_basis_policy_version": snapshot.valuation_policy_version,
                    "valuation_contract_version": snapshot.contract_version,
                    "valuation_assurance": wire.get("valuation_assurance"),
                    "freshness_policy_version": snapshot.freshness_policy_version,
                    "materiality_policy_version": snapshot.materiality_policy_version,
                    "canonical_snapshot": wire,
                    "persistence_state": "draft",
                    "created_at": wire["created_at"],
                },
            )
        ]
        capital = (
            ("basic_shares_outstanding", basic),
            ("fully_diluted_shares", diluted),
            ("cash", cash),
            ("debt", debt),
        )
        records.extend(
            _capital_record(snapshot, input_type, measure)
            for input_type, measure in capital
            if measure is not None
        )
        records.extend(
            _dilution_record(snapshot, _mapping(instrument))
            for instrument in _sequence(wire["dilution_instruments"])
        )
        calculations = [
            _fully_diluted_calculation(diluted),
            market_cap,
            enterprise_value,
        ]
        records.extend(
            _calculation_record(snapshot, calculation)
            for calculation in calculations
            if calculation is not None
        )
        records.extend(
            _materiality_record(snapshot, _mapping(assessment))
            for assessment in _sequence(wire["evidence_materiality"])
        )
        return records


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("expected object")
    return value


def _optional_mapping(value: object) -> Mapping[str, Any] | None:
    return None if value is None else _mapping(value)


def _sequence(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError("expected array")
    return value


def _capital_record(
    snapshot: ValuationSnapshot,
    input_type: str,
    measure: Mapping[str, Any],
) -> tuple[str, str, Mapping[str, Any]]:
    input_id = str(measure["input_id"])
    return (
        "iros_valuation_capital_inputs",
        "operator_id,valuation_snapshot_id,input_id",
        {
            "id": stable_id(
                snapshot.operator_id,
                "valuation-capital-input",
                f"{snapshot.id}:{input_id}",
            ),
            "operator_id": snapshot.operator_id,
            "valuation_snapshot_id": snapshot.id,
            "input_id": input_id,
            "input_type": input_type,
            "instrument_type": None,
            "value": measure["value"],
            "unit": measure["unit"],
            "effective_at": measure["effective_at"],
            "calculation_method": measure["calculation_method"],
            "formula": measure["formula"],
            "calculation_id": measure["calculation_id"],
            "input_ids": measure["input_ids"],
            "supporting_evidence_ids": measure["supporting_evidence_ids"],
            "freshness_state": measure["freshness_state"],
            "freshness_reason_code": measure["freshness_reason_code"],
            "freshness_policy_version": measure["freshness_policy_version"],
            "canonical_payload": measure,
            "created_at": snapshot.created_at.isoformat(),
        },
    )


def _dilution_record(
    snapshot: ValuationSnapshot,
    instrument: Mapping[str, Any],
) -> tuple[str, str, Mapping[str, Any]]:
    input_id = str(instrument["instrument_id"])
    return (
        "iros_valuation_capital_inputs",
        "operator_id,valuation_snapshot_id,input_id",
        {
            "id": stable_id(
                snapshot.operator_id,
                "valuation-capital-input",
                f"{snapshot.id}:{input_id}",
            ),
            "operator_id": snapshot.operator_id,
            "valuation_snapshot_id": snapshot.id,
            "input_id": input_id,
            "input_type": "dilution_instrument",
            "instrument_type": instrument["instrument_type"],
            "value": instrument["diluted_share_increment"],
            "unit": "shares",
            "effective_at": instrument["effective_at"],
            "calculation_method": "reported",
            "formula": None,
            "calculation_id": None,
            "input_ids": [],
            "supporting_evidence_ids": instrument["supporting_evidence_ids"],
            "freshness_state": None,
            "freshness_reason_code": None,
            "freshness_policy_version": None,
            "canonical_payload": instrument,
            "created_at": snapshot.created_at.isoformat(),
        },
    )


def _fully_diluted_calculation(
    diluted: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if diluted is None or diluted["calculation_id"] is None:
        return None
    return {
        "value": diluted["value"],
        "unit": diluted["unit"],
        "formula": diluted["formula"],
        "formula_version": "fully-diluted-shares-v1",
        "input_ids": diluted["input_ids"],
        "calculation_id": diluted["calculation_id"],
        "supporting_evidence_ids": diluted["supporting_evidence_ids"],
    }


def _calculation_record(
    snapshot: ValuationSnapshot,
    calculation: Mapping[str, Any],
) -> tuple[str, str, Mapping[str, Any]]:
    calculation_id = str(calculation["calculation_id"])
    if calculation["formula_version"] == "fully-diluted-shares-v1":
        calculation_type = "fully_diluted_shares"
    elif calculation["formula_version"] == "market-capitalization-v1":
        calculation_type = "market_capitalization"
    else:
        calculation_type = "enterprise_value"
    return (
        "iros_valuation_calculation_results",
        "operator_id,valuation_snapshot_id,calculation_id",
        {
            "id": stable_id(
                snapshot.operator_id,
                "valuation-calculation-result",
                f"{snapshot.id}:{calculation_id}",
            ),
            "operator_id": snapshot.operator_id,
            "valuation_snapshot_id": snapshot.id,
            "calculation_id": calculation_id,
            "calculation_type": calculation_type,
            "value": calculation["value"],
            "unit": calculation["unit"],
            "formula": calculation["formula"],
            "formula_version": calculation["formula_version"],
            "input_ids": calculation["input_ids"],
            "supporting_evidence_ids": calculation["supporting_evidence_ids"],
            "canonical_payload": calculation,
            "created_at": snapshot.created_at.isoformat(),
        },
    )


def _materiality_record(
    snapshot: ValuationSnapshot,
    assessment: Mapping[str, Any],
) -> tuple[str, str, Mapping[str, Any]]:
    evidence_id = str(assessment["evidence_id"])
    return (
        "iros_valuation_materiality_assessments",
        "operator_id,valuation_snapshot_id,evidence_id",
        {
            "id": stable_id(
                snapshot.operator_id,
                "valuation-materiality-assessment",
                f"{snapshot.id}:{evidence_id}",
            ),
            "operator_id": snapshot.operator_id,
            "valuation_snapshot_id": snapshot.id,
            "evidence_id": evidence_id,
            "publication_at": assessment["publication_at"],
            "timing_state": assessment["timing_state"],
            "market_materiality": assessment["market_materiality"],
            "materiality_reason_code": assessment["materiality_reason_code"],
            "materiality_policy_version": assessment["materiality_policy_version"],
            "affected_domains": assessment["affected_domains"],
            "canonical_payload": assessment,
            "created_at": snapshot.created_at.isoformat(),
        },
    )


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def _capital_from_wire(payload: Mapping[str, Any]) -> CapitalStructureInput:
    basic = _mapping(payload["basic_shares_outstanding"])
    diluted = _mapping(payload["fully_diluted_shares"])
    included_cash = _mapping(payload["cash"])
    debt = _mapping(payload["debt"])
    cash_treatment = _mapping(payload["cash_treatment"])
    reported_cash = _mapping(cash_treatment["reported_cash"])
    restricted_cash = _mapping(cash_treatment["restricted_cash"])
    other_claims = _mapping(payload["other_included_claims"])
    return CapitalStructureInput(
        basic_shares_outstanding=str(basic["value"]),
        fully_diluted_shares=str(diluted["value"]),
        cash=str(reported_cash["value"]),
        restricted_cash=str(restricted_cash["value"]),
        restricted_cash_treatment=str(cash_treatment["restricted_cash_treatment"]),
        debt=str(debt["value"]),
        other_included_claims=str(other_claims["value"]),
        included_cash=str(included_cash["value"]),
        currency=str(payload["currency"]),
        basic_shares_effective_at=_required_timestamp(basic["effective_at"]),
        fully_diluted_shares_effective_at=_required_timestamp(diluted["effective_at"]),
        cash_effective_at=_required_timestamp(reported_cash["effective_at"]),
        restricted_cash_effective_at=_required_timestamp(
            restricted_cash["effective_at"]
        ),
        included_cash_effective_at=_required_timestamp(included_cash["effective_at"]),
        debt_effective_at=_required_timestamp(debt["effective_at"]),
        other_included_claims_effective_at=_required_timestamp(
            other_claims["effective_at"]
        ),
        basic_shares_evidence_ids=tuple(basic["supporting_evidence_ids"]),
        diluted_shares_evidence_ids=tuple(diluted["supporting_evidence_ids"]),
        cash_evidence_ids=tuple(reported_cash["supporting_evidence_ids"]),
        restricted_cash_evidence_ids=tuple(restricted_cash["supporting_evidence_ids"]),
        debt_evidence_ids=tuple(debt["supporting_evidence_ids"]),
        other_included_claims_evidence_ids=tuple(
            other_claims["supporting_evidence_ids"]
        ),
        basic_shares_freshness_state=str(basic["freshness_state"]),
        basic_shares_freshness_reason_code=str(basic["freshness_reason_code"]),
        diluted_shares_freshness_state=str(diluted["freshness_state"]),
        diluted_shares_freshness_reason_code=str(diluted["freshness_reason_code"]),
        cash_freshness_state=str(reported_cash["freshness_state"]),
        cash_freshness_reason_code=str(reported_cash["freshness_reason_code"]),
        restricted_cash_freshness_state=str(restricted_cash["freshness_state"]),
        restricted_cash_freshness_reason_code=str(
            restricted_cash["freshness_reason_code"]
        ),
        debt_freshness_state=str(debt["freshness_state"]),
        debt_freshness_reason_code=str(debt["freshness_reason_code"]),
        other_included_claims_freshness_state=str(other_claims["freshness_state"]),
        other_included_claims_freshness_reason_code=str(
            other_claims["freshness_reason_code"]
        ),
        freshness_policy_version=str(basic["freshness_policy_version"]),
        dilution_instruments=tuple(
            DilutionInstrument(
                instrument_id=str(item["instrument_id"]),
                instrument_type=str(item["instrument_type"]),
                diluted_share_increment=str(item["diluted_share_increment"]),
                effective_at=_required_timestamp(item["effective_at"]),
                supporting_evidence_ids=tuple(item["supporting_evidence_ids"]),
            )
            for raw in _sequence(payload["dilution_instruments"])
            for item in (_mapping(raw),)
        ),
    )


def _derived_from_wire(value: object) -> DerivedValuation | None:
    payload = _optional_mapping(value)
    if payload is None:
        return None
    return DerivedValuation(
        value=str(payload["value"]),
        unit=str(payload["unit"]),
        formula=str(payload["formula"]),
        formula_version=str(payload["formula_version"]),
        input_ids=tuple(payload["input_ids"]),
        calculation_id=str(payload["calculation_id"]),
        supporting_evidence_ids=tuple(payload["supporting_evidence_ids"]),
    )


def _required_timestamp(value: object) -> datetime:
    parsed = _timestamp(str(value))
    if parsed is None:
        raise ValueError("timestamp required")
    return parsed


def _snapshot_from_wire(payload: Mapping[str, Any]) -> ValuationSnapshot:
    contract_version = str(payload["contract_version"])
    if contract_version not in {
        "valuation_snapshot.v1",
        "valuation_snapshot.personal_research.v1",
    }:
        raise ValueError("unsupported valuation snapshot contract")
    personal_research = contract_version == "valuation_snapshot.personal_research.v1"
    assurance = None
    if personal_research:
        raw_assurance = _mapping(payload["valuation_assurance"])
        assurance = ValuationAssurance(
            level=str(raw_assurance["level"]),
            usage_scope=str(raw_assurance["usage_scope"]),
            rights_assurance=str(raw_assurance["rights_assurance"]),
            limitation_codes=tuple(raw_assurance["limitation_codes"]),
        )
        if (
            assurance.level != "personal_research"
            or assurance.usage_scope != "private_personal_research"
            or assurance.rights_assurance != "not_independently_verified"
            or not {
                "not_primary_venue_official_close",
                "not_institutional_grade",
                "not_for_trade_execution",
            }.issubset(assurance.limitation_codes)
        ):
            raise ValueError("invalid personal valuation assurance")
    price_basis = _optional_mapping(payload["price_basis"])
    source_references = tuple(
        ValuationSourceReference(
            source_reference_id=str(item["source_reference_id"]),
            source_type=str(item["source_type"]),
            provider=str(item["provider"]),
            locator=str(item["locator"]),
            published_at=_timestamp(item["published_at"]),
            retrieved_at=_required_timestamp(item["retrieved_at"]),
            effective_at=_timestamp(item["effective_at"]),
            provider_plan_id=(
                str(item["provider_plan_id"])
                if item.get("provider_plan_id") is not None
                else None
            ),
            response_sha256=(
                str(item["response_sha256"])
                if item.get("response_sha256") is not None
                else None
            ),
            provider_contract_status=(
                str(item["provider_contract_status"])
                if item.get("provider_contract_status") is not None
                else None
            ),
            provider_limitation_codes=tuple(
                str(code)
                for code in item.get("provider_limitation_codes", ())
            ),
        )
        for raw in _sequence(payload["source_references"])
        for item in (_mapping(raw),)
    )
    provider_by_reference = {
        source.source_reference_id: source.provider for source in source_references
    }
    price = None
    if price_basis is not None:
        provider_reference_id = str(price_basis["provider_source_reference_id"])
        if provider_reference_id not in provider_by_reference:
            raise ValueError("price provider source reference is unresolved")
        price = PriceObservation(
            price_type=str(price_basis["price_type"]),
            session_type=str(price_basis["session_type"]),
            session_date=date.fromisoformat(str(price_basis["session_date"])),
            primary_listing_exchange=str(price_basis["primary_listing_exchange"]),
            price=str(price_basis["share_price"]),
            currency=str(payload["currency"]),
            official_close_timestamp=_required_timestamp(
                price_basis[
                    "price_timestamp"
                    if personal_research
                    else "official_close_timestamp"
                ]
            ),
            market_status=str(price_basis["market_status"]),
            corporate_action_adjustment_status=str(
                price_basis["corporate_action_adjustment_status"]
            ),
            provider=provider_by_reference[provider_reference_id],
            source_reference=provider_reference_id,
            halt_verification_status=str(
                price_basis.get("halt_verification_status", "verified_not_halted")
            ),
        )
    cutoff = _required_timestamp(payload["as_of_cutoff"])
    close = price.official_close_timestamp if price is not None else cutoff
    session_date = price.session_date if price is not None else cutoff.date()
    session = MarketSession(
        session_date=session_date,
        opens_at=close - timedelta(hours=6, minutes=30),
        closes_at=close,
        session_type=(
            price.session_type if price is not None else "regular_us_trading_session"
        ),
        primary_listing_exchange=(
            price.primary_listing_exchange if price is not None else "unknown"
        ),
        early_close=False,
        calendar_version=(
            str(price_basis["market_calendar_version"])
            if price_basis is not None
            else "unknown"
        ),
    )
    corporate = _mapping(payload["corporate_action_reconciliation"])
    return ValuationSnapshot(
        id=str(payload["id"]),
        operator_id=str(payload["operator_id"]),
        research_run_id=str(payload["research_run_id"]),
        evidence_bundle_id=str(payload["evidence_bundle_id"]),
        evidence_bundle_hash=str(payload["evidence_bundle_hash"]),
        security_id=str(payload["security_id"]),
        as_of_cutoff=cutoff,
        price=price,
        session=session,
        capital=_capital_from_wire(payload),
        market_capitalization=_derived_from_wire(payload["market_capitalization"]),
        enterprise_value=_derived_from_wire(payload["enterprise_value"]),
        calculation_ids=tuple(payload["calculation_ids"]),
        corporate_action=CorporateActionReconciliation(
            event_id=corporate["event_id"],
            action_type=str(corporate["event_type"]),
            effective_at=_timestamp(corporate["effective_at"]),
            price_adjustment_status=str(corporate["price_adjustment_status"]),
            share_count_adjustment_status=str(
                corporate["share_count_adjustment_status"]
            ),
            reconciliation_result=str(corporate["reconciliation_result"]),
        ),
        materiality_assessments=tuple(
            MaterialityAssessment(
                evidence_id=str(item["evidence_id"]),
                publication_at=_timestamp(item["publication_at"]),
                market_materiality=str(item["market_materiality"]),
                materiality_reason_code=str(item["materiality_reason_code"]),
                affected_domains=tuple(item["affected_domains"]),
                policy_version=str(item["materiality_policy_version"]),
                timing_state=str(item["timing_state"]),
            )
            for raw in _sequence(payload["evidence_materiality"])
            for item in (_mapping(raw),)
        ),
        source_references=source_references,
        snapshot_status=str(payload["snapshot_status"]),
        invalid_reason_codes=tuple(payload["invalid_reason_codes"]),
        price_information_state=str(payload["price_information_state"]),
        market_relative_analysis_permitted=bool(
            payload["market_relative_analysis_permitted"]
        ),
        valuation_policy_version=str(payload["price_basis_policy_version"]),
        freshness_policy_version=str(payload["freshness_policy_version"]),
        materiality_policy_version=str(payload["materiality_policy_version"]),
        created_at=_required_timestamp(payload["created_at"]),
        contract_version=contract_version,
        valuation_assurance=assurance,
    )


__all__ = ["SupabaseValuationSnapshotRepository"]
