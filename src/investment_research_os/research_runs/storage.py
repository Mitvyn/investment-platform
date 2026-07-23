from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import re
from typing import Any
from urllib.parse import urlencode

from investment_research_os.ids import stable_id
from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)

from . import (
    EligibilityCheck,
    EligibilityResult,
    ResearchRun,
    RULE_IDS,
    SecurityIdentity,
)


class SupabaseResearchRunRepository:
    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def save(self, run: ResearchRun) -> ResearchRun:
        for table, conflict_columns, merge_duplicates, record in self._records(run):
            url = (
                f"{self.settings.url.rstrip('/')}/rest/v1/{table}?"
                f"{urlencode({'on_conflict': conflict_columns})}"
            )
            resolution = "merge-duplicates" if merge_duplicates else "ignore-duplicates"
            response = self.transport.request_json(
                "POST",
                url,
                headers={
                    "Content-Type": "application/json",
                    "Prefer": f"resolution={resolution},return=minimal",
                    "apikey": self.settings.secret_key,
                },
                payload=record,
            )
            if response.status not in (200, 201, 204):
                raise EvidenceStorageError(
                    f"research run store returned HTTP {response.status} for {table}"
                )
        self._finalize(run)
        persisted = self.get(run.operator_id, run.id)
        if persisted is None or persisted.as_dict() != run.as_dict():
            raise EvidenceStorageError(
                "persisted research run does not match requested contract"
            )
        return persisted

    def _finalize(self, run: ResearchRun) -> None:
        query = urlencode(
            {
                "id": f"eq.{run.id}",
                "operator_id": f"eq.{run.operator_id}",
                "persistence_state": "eq.draft",
            }
        )
        response = self.transport.request_json(
            "PATCH",
            f"{self.settings.url.rstrip('/')}/rest/v1/iros_research_runs?{query}",
            headers={
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
                "apikey": self.settings.secret_key,
            },
            payload={"persistence_state": "complete"},
        )
        if response.status not in (200, 204):
            raise EvidenceStorageError(
                "research run store returned "
                f"HTTP {response.status} while finalizing iros_research_runs"
            )

    def get(self, operator_id: str, run_id: str) -> ResearchRun | None:
        select_fields = (
            "operator_id,research_run_id,security_id,security_identity_snapshot,"
            "question_type,question_type_version_id,workflow_config_version_id,"
            "thesis_contract_id,as_of_cutoff,operator_focus_original,"
            "operator_focus_normalized,status,idempotency_key,created_at,"
            "eligibility_policy_version,eligible,evaluated_at,check_ordinal,"
            "rule_id,rule_version,passed,evidence_reference,reason_code,"
            "explanation,check_evaluated_at"
        )
        query = urlencode(
            {
                "operator_id": f"eq.{operator_id}",
                "research_run_id": f"eq.{run_id}",
                "select": select_fields,
                "order": "check_ordinal.asc",
            }
        )
        url = (
            f"{self.settings.url.rstrip('/')}/rest/v1/"
            f"iros_v_research_run_eligibility?{query}"
        )
        response = self.transport.request_json(
            "GET",
            url,
            headers={"apikey": self.settings.secret_key},
        )
        if response.status != 200:
            raise EvidenceStorageError(
                "research run store returned "
                f"HTTP {response.status} for iros_v_research_run_eligibility"
            )
        if not isinstance(response.payload, list):
            raise EvidenceStorageError("research run view returned invalid payload")
        if not response.payload:
            return None
        return self._from_view_rows(response.payload)

    @staticmethod
    def _records(
        run: ResearchRun,
    ) -> list[tuple[str, str, bool, dict[str, Any]]]:
        evaluation_id = stable_id(
            run.operator_id,
            "eligibility-evaluation",
            run.id,
        )
        security_snapshot = asdict(run.security_identity)
        records: list[tuple[str, str, bool, dict[str, Any]]] = []
        if _has_verified_canonical_identity(run):
            records.append(
                (
                    "iros_securities",
                    "operator_id,id",
                    False,
                    {
                        "operator_id": run.operator_id,
                        "id": run.security_id,
                        "cik": run.security_identity.cik,
                        "issuer_name": run.security_identity.issuer_name,
                        "symbol": run.security_identity.symbol,
                        "primary_listing_exchange": (
                            run.security_identity.primary_listing_exchange
                        ),
                        "updated_at": run.created_at.isoformat(),
                    },
                )
            )
        records.extend(
            [
                (
                    "iros_research_runs",
                    "id",
                    False,
                    {
                        "id": run.id,
                        "operator_id": run.operator_id,
                        "ticker": run.security_identity.symbol,
                        "run_type": "research_committee",
                        "trigger_type": "manual",
                        "status": run.status,
                        "idempotency_key": run.idempotency_key,
                        "started_at": run.created_at.isoformat(),
                        "finished_at": run.eligibility.evaluated_at.isoformat(),
                        "security_id": run.security_id,
                        "question_type_version_id": run.question_type_version,
                        "workflow_config_version_id": run.workflow_config_version,
                        "thesis_contract_id": run.thesis_contract_id,
                        "as_of_cutoff": run.as_of_cutoff.isoformat(),
                        "operator_focus_original": run.operator_focus_original,
                        "operator_focus_normalized": run.operator_focus_normalized,
                        "security_identity_snapshot": security_snapshot,
                        "persistence_state": "draft",
                    },
                ),
                (
                    "iros_eligibility_evaluations",
                    "id",
                    False,
                    {
                        "id": evaluation_id,
                        "operator_id": run.operator_id,
                        "research_run_id": run.id,
                        "security_id": run.security_id,
                        "policy_version": run.eligibility.policy_version,
                        "eligible": run.eligibility.eligible,
                        "evaluated_at": run.eligibility.evaluated_at.isoformat(),
                    },
                ),
            ]
        )
        records.extend(
            (
                "iros_eligibility_checks",
                "id",
                False,
                {
                    "id": stable_id(
                        run.operator_id,
                        "eligibility-check",
                        f"{evaluation_id}:{check.rule_id}",
                    ),
                    "operator_id": run.operator_id,
                    "eligibility_evaluation_id": evaluation_id,
                    "ordinal": ordinal,
                    "rule_id": check.rule_id,
                    "rule_version": check.rule_version,
                    "passed": check.passed,
                    "evidence_reference": check.evidence_reference,
                    "reason_code": check.reason_code,
                    "explanation": check.explanation,
                    "evaluated_at": check.evaluated_at.isoformat(),
                },
            )
            for ordinal, check in enumerate(run.eligibility.checks, start=1)
        )
        return records

    @staticmethod
    def _from_view_rows(rows: list[Any]) -> ResearchRun:
        if not all(isinstance(row, dict) for row in rows):
            raise EvidenceStorageError("research run view returned invalid rows")
        ordered = sorted(rows, key=lambda row: row["check_ordinal"])
        first = ordered[0]
        identity = first["security_identity_snapshot"]
        if not isinstance(identity, dict):
            raise EvidenceStorageError(
                "research run view returned invalid security identity"
            )
        checks = tuple(
            EligibilityCheck(
                rule_id=row["rule_id"],
                rule_version=row["rule_version"],
                passed=row["passed"],
                evidence_reference=row["evidence_reference"],
                reason_code=row["reason_code"],
                explanation=row["explanation"],
                evaluated_at=_parse_timestamp(row["check_evaluated_at"]),
            )
            for row in ordered
        )
        if (
            tuple(check.rule_id for check in checks) != RULE_IDS
            or any(check.rule_version != f"{check.rule_id}.v1" for check in checks)
            or first["eligible"] != all(check.passed for check in checks)
        ):
            raise EvidenceStorageError(
                "research run view returned invalid eligibility contract"
            )
        return ResearchRun(
            id=first["research_run_id"],
            operator_id=first["operator_id"],
            security_id=first["security_id"],
            security_identity=SecurityIdentity(
                id=identity["id"],
                cik=identity["cik"],
                issuer_name=identity["issuer_name"],
                symbol=identity["symbol"],
                primary_listing_exchange=identity["primary_listing_exchange"],
            ),
            question_type=first["question_type"],
            question_type_version=first["question_type_version_id"],
            workflow_config_version=first["workflow_config_version_id"],
            thesis_contract_id=first["thesis_contract_id"],
            as_of_cutoff=_parse_timestamp(first["as_of_cutoff"]),
            operator_focus_original=first["operator_focus_original"],
            operator_focus_normalized=first["operator_focus_normalized"],
            status=first["status"],
            idempotency_key=first["idempotency_key"],
            eligibility=EligibilityResult(
                policy_version=first["eligibility_policy_version"],
                eligible=first["eligible"],
                checks=checks,
                evaluated_at=_parse_timestamp(first["evaluated_at"]),
            ),
            created_at=_parse_timestamp(first["created_at"]),
        )


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _has_verified_canonical_identity(run: ResearchRun) -> bool:
    checks = {check.rule_id: check.passed for check in run.eligibility.checks}
    identity = run.security_identity
    return (
        checks.get("security_identity_verified") is True
        and checks.get("cik_match") is True
        and re.fullmatch(r"[0-9]{10}", identity.cik) is not None
        and bool(identity.issuer_name.strip())
        and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", identity.symbol) is not None
        and bool(identity.primary_listing_exchange.strip())
    )


__all__ = ["SupabaseResearchRunRepository"]
