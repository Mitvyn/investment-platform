from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from .submissions import SecSubmissionFiling, SecSubmissionsSnapshot


SEC_FILING_POLICY_VERSION = "biotech-required-sec-filings-v1"
REQUIREMENT_IDS = (
    "sec_latest_annual_report",
    "sec_latest_periodic_report",
    "sec_post_periodic_current_reports",
    "sec_financing_filing_scan",
)
_FINANCING_FORMS = frozenset(
    {
        "S-1",
        "S-1/A",
        "S-3",
        "S-3/A",
        "S-3ASR",
        "424B3",
        "424B4",
        "424B5",
        "POS AM",
    }
)


@dataclass(frozen=True, slots=True)
class SecFilingRequirementResult:
    requirement_id: str
    state: str
    reason_code: str
    selected_accessions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SecFilingSelection:
    policy_version: str
    operator_id: str
    security_id: str
    cik: str
    as_of_cutoff: datetime
    coverage_state: str
    selected_filings: tuple[SecSubmissionFiling, ...]
    requirement_results: tuple[SecFilingRequirementResult, ...]
    reason_codes: tuple[str, ...]
    eligibility_coverage: frozenset[str]


class RequiredSecFilingSelector:
    def select(self, snapshot: SecSubmissionsSnapshot) -> SecFilingSelection:
        if not snapshot.submission_history_complete:
            return self._indeterminate(
                snapshot,
                reason_code="sec_submission_history_incomplete",
            )
        relevant_forms = {
            "10-K",
            "10-K/A",
            "10-Q",
            "10-Q/A",
            "8-K",
            "8-K/A",
            *_FINANCING_FORMS,
        }
        if any(
            filing.form in relevant_forms
            and filing.publication_state
            in {"date_only", "timezone_ambiguous", "unavailable"}
            for filing in snapshot.excluded_filings
        ):
            return self._indeterminate(
                snapshot,
                reason_code=("sec_required_filing_publication_indeterminate"),
            )

        filings = self._deduplicate(snapshot.included_filings)
        annual = self._latest_base_with_amendments(
            filings,
            base_form="10-K",
            amendment_form="10-K/A",
        )
        if not annual:
            if any(filing.form == "10-K/A" for filing in filings):
                return self._indeterminate(
                    snapshot,
                    reason_code="sec_amendment_base_missing",
                )
            return self._missing_annual(snapshot)
        annual_base = annual[0]
        if not self._within_days(
            annual_base,
            snapshot.as_of_cutoff,
            days=550,
        ):
            return self._blocked(
                snapshot,
                reason_code="sec_annual_report_stale",
            )

        annual_report_date = annual_base.report_date
        quarterly_candidates = tuple(
            filing
            for filing in filings
            if filing.form in {"10-Q", "10-Q/A"}
            and (
                annual_report_date is None
                or filing.report_date is None
                or filing.report_date > annual_report_date
            )
        )
        periodic = self._latest_base_with_amendments(
            quarterly_candidates,
            base_form="10-Q",
            amendment_form="10-Q/A",
        )
        if not periodic and any(
            filing.form == "10-Q/A" for filing in quarterly_candidates
        ):
            return self._indeterminate(
                snapshot,
                reason_code="sec_amendment_base_missing",
            )
        if not periodic:
            periodic = annual
        periodic_base = periodic[0]
        if not self._within_days(
            periodic_base,
            snapshot.as_of_cutoff,
            days=200,
        ):
            return self._periodic_blocked(
                snapshot,
                annual=annual,
                reason_code="sec_periodic_report_stale",
            )

        periodic_time = self._publication_time(periodic_base)
        current_reports = tuple(
            sorted(
                (
                    filing
                    for filing in filings
                    if filing.form in {"8-K", "8-K/A"}
                    and self._publication_time(filing) > periodic_time
                ),
                key=self._filing_key,
            )
        )
        financing_cutoff = snapshot.as_of_cutoff.date() - timedelta(days=1096)
        financing = tuple(
            sorted(
                (
                    filing
                    for filing in filings
                    if filing.form in _FINANCING_FORMS
                    and filing.filing_date >= financing_cutoff
                ),
                key=self._filing_key,
            )
        )
        selected = self._canonical_unique(
            (*annual, *periodic, *current_reports, *financing)
        )
        annual_accessions = tuple(filing.accession_number for filing in annual)
        periodic_accessions = tuple(filing.accession_number for filing in periodic)
        current_accessions = tuple(
            filing.accession_number for filing in current_reports
        )
        financing_accessions = tuple(filing.accession_number for filing in financing)
        requirements = (
            SecFilingRequirementResult(
                "sec_latest_annual_report",
                "satisfied",
                "sec_annual_report_selected",
                annual_accessions,
            ),
            SecFilingRequirementResult(
                "sec_latest_periodic_report",
                "satisfied",
                "sec_periodic_report_selected",
                periodic_accessions,
            ),
            SecFilingRequirementResult(
                "sec_post_periodic_current_reports",
                "satisfied",
                (
                    "sec_post_periodic_search_complete"
                    if current_reports
                    else "sec_no_post_periodic_current_reports"
                ),
                current_accessions,
            ),
            SecFilingRequirementResult(
                "sec_financing_filing_scan",
                "satisfied",
                (
                    "sec_financing_search_complete"
                    if financing
                    else "sec_no_financing_forms_in_window"
                ),
                financing_accessions,
            ),
        )
        return self._result(
            snapshot,
            coverage_state="complete",
            selected=selected,
            requirements=requirements,
            reason_codes=tuple(requirement.reason_code for requirement in requirements)
            + ("sec_required_filings_complete",),
        )

    @staticmethod
    def _deduplicate(
        filings: tuple[SecSubmissionFiling, ...],
    ) -> tuple[SecSubmissionFiling, ...]:
        by_accession: dict[str, SecSubmissionFiling] = {}
        for filing in filings:
            existing = by_accession.get(filing.accession_number)
            if existing is not None and existing != filing:
                raise ValueError("sec_filing_identity_conflict")
            by_accession[filing.accession_number] = filing
        return tuple(by_accession.values())

    @classmethod
    def _latest_base_with_amendments(
        cls,
        filings: tuple[SecSubmissionFiling, ...],
        *,
        base_form: str,
        amendment_form: str,
    ) -> tuple[SecSubmissionFiling, ...]:
        bases = tuple(filing for filing in filings if filing.form == base_form)
        if not bases:
            return ()
        base = max(bases, key=cls._filing_key)
        amendments = tuple(
            sorted(
                (
                    filing
                    for filing in filings
                    if filing.form == amendment_form
                    and filing.report_date == base.report_date
                ),
                key=cls._filing_key,
            )
        )
        return (base, *amendments)

    @staticmethod
    def _publication_time(filing: SecSubmissionFiling) -> datetime:
        if filing.published_at is not None:
            return filing.published_at
        if filing.publication_date is None:
            raise ValueError("sec_required_filing_publication_indeterminate")
        return datetime.combine(
            filing.publication_date,
            time.min,
            tzinfo=UTC,
        )

    @classmethod
    def _filing_key(
        cls,
        filing: SecSubmissionFiling,
    ) -> tuple[date, datetime, str]:
        return (
            filing.report_date or filing.filing_date,
            cls._publication_time(filing),
            filing.accession_number,
        )

    @staticmethod
    def _within_days(
        filing: SecSubmissionFiling,
        cutoff: datetime,
        *,
        days: int,
    ) -> bool:
        return (
            cutoff.astimezone(UTC) - RequiredSecFilingSelector._publication_time(filing)
        ) <= timedelta(days=days)

    @staticmethod
    def _canonical_unique(
        filings: tuple[SecSubmissionFiling, ...],
    ) -> tuple[SecSubmissionFiling, ...]:
        selected: list[SecSubmissionFiling] = []
        seen: set[str] = set()
        for filing in filings:
            if filing.accession_number in seen:
                continue
            seen.add(filing.accession_number)
            selected.append(filing)
        return tuple(selected)

    @classmethod
    def _missing_annual(
        cls,
        snapshot: SecSubmissionsSnapshot,
    ) -> SecFilingSelection:
        return cls._blocked(
            snapshot,
            reason_code="sec_required_annual_report_missing",
        )

    @classmethod
    def _blocked(
        cls,
        snapshot: SecSubmissionsSnapshot,
        *,
        reason_code: str,
    ) -> SecFilingSelection:
        return cls._result(
            snapshot,
            coverage_state="incomplete",
            selected=(),
            requirements=tuple(
                SecFilingRequirementResult(
                    requirement_id=requirement_id,
                    state=(
                        "missing"
                        if requirement_id == "sec_latest_annual_report"
                        else "indeterminate"
                    ),
                    reason_code=reason_code,
                    selected_accessions=(),
                )
                for requirement_id in REQUIREMENT_IDS
            ),
            reason_codes=(reason_code,),
        )

    @classmethod
    def _indeterminate(
        cls,
        snapshot: SecSubmissionsSnapshot,
        *,
        reason_code: str,
    ) -> SecFilingSelection:
        return cls._result(
            snapshot,
            coverage_state="indeterminate",
            selected=(),
            requirements=tuple(
                SecFilingRequirementResult(
                    requirement_id=requirement_id,
                    state="indeterminate",
                    reason_code=reason_code,
                    selected_accessions=(),
                )
                for requirement_id in REQUIREMENT_IDS
            ),
            reason_codes=(reason_code,),
        )

    @classmethod
    def _periodic_blocked(
        cls,
        snapshot: SecSubmissionsSnapshot,
        *,
        annual: tuple[SecSubmissionFiling, ...],
        reason_code: str,
    ) -> SecFilingSelection:
        annual_accessions = tuple(filing.accession_number for filing in annual)
        return cls._result(
            snapshot,
            coverage_state="incomplete",
            selected=annual,
            requirements=(
                SecFilingRequirementResult(
                    "sec_latest_annual_report",
                    "satisfied",
                    "sec_annual_report_selected",
                    annual_accessions,
                ),
                SecFilingRequirementResult(
                    "sec_latest_periodic_report",
                    "missing",
                    reason_code,
                    (),
                ),
                SecFilingRequirementResult(
                    "sec_post_periodic_current_reports",
                    "indeterminate",
                    reason_code,
                    (),
                ),
                SecFilingRequirementResult(
                    "sec_financing_filing_scan",
                    "indeterminate",
                    reason_code,
                    (),
                ),
            ),
            reason_codes=(
                "sec_annual_report_selected",
                reason_code,
            ),
        )

    @staticmethod
    def _result(
        snapshot: SecSubmissionsSnapshot,
        *,
        coverage_state: str,
        selected: tuple[SecSubmissionFiling, ...],
        requirements: tuple[SecFilingRequirementResult, ...],
        reason_codes: tuple[str, ...],
    ) -> SecFilingSelection:
        return SecFilingSelection(
            policy_version=SEC_FILING_POLICY_VERSION,
            operator_id=snapshot.operator_id,
            security_id=snapshot.security_id,
            cik=snapshot.cik,
            as_of_cutoff=snapshot.as_of_cutoff,
            coverage_state=coverage_state,
            selected_filings=selected,
            requirement_results=requirements,
            reason_codes=reason_codes,
            eligibility_coverage=(
                frozenset({"required_sec_filings"})
                if coverage_state == "complete"
                else frozenset()
            ),
        )


__all__ = [
    "REQUIREMENT_IDS",
    "RequiredSecFilingSelector",
    "SEC_FILING_POLICY_VERSION",
    "SecFilingRequirementResult",
    "SecFilingSelection",
]
