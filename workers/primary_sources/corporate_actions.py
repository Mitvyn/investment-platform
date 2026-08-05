from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlparse

from .models import PrimarySourceRequest
from .pipeline import PrimaryEvidencePassage
from .share_growth import CorporateActionReconciliation


CORPORATE_ACTION_POLICY_VERSION = "financing-corporate-actions-v2"
_ACCESSION_PREFIX = re.compile(r"^\d{10}-\d{2}-\d{6}/")
_NO_ACTION = re.compile(
    r"^From (?P<from>\d{4}-\d{2}-\d{2}) through "
    r"(?P<to>\d{4}-\d{2}-\d{2}), no stock split, reverse stock split, "
    r"recapitalization, share class conversion, merger conversion, or other "
    r"corporate action changed the basic common share economic basis\.$",
    re.IGNORECASE,
)
_SPLIT = re.compile(
    r"^From (?P<from>\d{4}-\d{2}-\d{2}) through "
    r"(?P<to>\d{4}-\d{2}-\d{2}), a (?P<new>\d+)-for-(?P<old>\d+) "
    r"(?P<kind>forward|reverse) stock split became effective on "
    r"(?P<effective>\d{4}-\d{2}-\d{2}) and changed the basic common share "
    r"economic basis\.$",
    re.IGNORECASE,
)
_COMPARATIVE_SHARE_BASIS = re.compile(
    r"^Common stock, \$\s*(?P<par>\d+(?:\.\d+)?) par value; "
    r"(?P<authorized>[\d,]+) shares .*? authorized as of "
    r"(?P<to>[A-Z][a-z]+ \d{1,2}, \d{4}) and "
    r"(?P<from>[A-Z][a-z]+ \d{1,2}, \d{4}); "
    r"(?P<current>[\d,]+) shares .*? and "
    r"(?P<prior>[\d,]+) shares .*? issued and outstanding as of "
    r"(?P=to) and (?P=from), respectively\.?$",
    re.IGNORECASE,
)
_COMPARATIVE_BALANCE_SHEET_SHARE_BASIS = re.compile(
    r"^Common stock, \$\s*(?P<par>\d+(?:\.\d+)?) par value; "
    r"(?P<authorized>[\d,]+) shares authorized, "
    r"(?P<current>[\d,]+) and (?P<prior>[\d,]+) shares issued and "
    r"outstanding at (?P<to>[A-Z][a-z]+ \d{1,2}, \d{4}) and "
    r"(?P<from_year>\d{4}), respectively\.?$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CorporateActionAssessment:
    policy_version: str
    state: str
    reason_codes: tuple[str, ...]
    reconciliation: CorporateActionReconciliation | None


def _unresolved(reason_code: str) -> CorporateActionAssessment:
    return CorporateActionAssessment(
        policy_version=CORPORATE_ACTION_POLICY_VERSION,
        state="unresolved",
        reason_codes=(reason_code,),
        reconciliation=None,
    )


def _has_timezone(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _source_reason(
    passage: PrimaryEvidencePassage,
    cutoff: datetime,
) -> str | None:
    hostname = (urlparse(passage.canonical_url).hostname or "").casefold()
    if (
        passage.source_class != "financing"
        or passage.origin_policy_version != "sec-origin-v1"
        or hostname not in {"www.sec.gov", "data.sec.gov"}
        or _ACCESSION_PREFIX.match(passage.source_locator) is None
        or not passage.reference_key.strip()
        or not passage.passage_text.strip()
    ):
        return "corporate_action_source_invalid"
    available_at = passage.available_at or passage.publication_at
    if available_at is None or not _has_timezone(available_at):
        return "corporate_action_publication_time_indeterminate"
    if available_at > cutoff or (
        passage.publication_at is not None and passage.publication_at > cutoff
    ):
        return "corporate_action_evidence_after_cutoff"
    return None


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_filing_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%B %d, %Y").date()
    except ValueError:
        return None


def _format_decimal(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _parse_factor(
    passage: PrimaryEvidencePassage,
    *,
    from_period_end: date,
    to_period_end: date,
) -> tuple[str, str] | str:
    text = " ".join(passage.passage_text.split())
    match = _COMPARATIVE_SHARE_BASIS.fullmatch(text)
    balance_sheet_match = _COMPARATIVE_BALANCE_SHEET_SHARE_BASIS.fullmatch(text)
    if match or balance_sheet_match:
        assert match is not None or balance_sheet_match is not None
        if balance_sheet_match is not None:
            match = balance_sheet_match
            observed_to = _parse_filing_date(match.group("to"))
            try:
                observed_from = (
                    None
                    if observed_to is None
                    else observed_to.replace(year=int(match.group("from_year")))
                )
            except ValueError:
                observed_from = None
        else:
            assert match is not None
            observed_from = _parse_filing_date(match.group("from"))
            observed_to = _parse_filing_date(match.group("to"))
        if observed_from != from_period_end or observed_to != to_period_end:
            return "corporate_action_period_mismatch"
        try:
            par_value = Decimal(match.group("par"))
            authorized = Decimal(match.group("authorized").replace(",", ""))
            current = Decimal(match.group("current").replace(",", ""))
            prior = Decimal(match.group("prior").replace(",", ""))
        except InvalidOperation:
            return "corporate_action_comparative_basis_invalid"
        if (
            par_value <= 0
            or authorized <= 0
            or current <= 0
            or prior <= 0
            or current > authorized
            or prior > authorized
        ):
            return "corporate_action_comparative_basis_invalid"
        return "1", "corporate_action_comparative_basis_verified"
    if match := _NO_ACTION.fullmatch(text):
        observed_from = _parse_date(match.group("from"))
        observed_to = _parse_date(match.group("to"))
        if observed_from != from_period_end or observed_to != to_period_end:
            return "corporate_action_period_mismatch"
        return "1", "corporate_action_no_action_verified"
    if match := _SPLIT.fullmatch(text):
        observed_from = _parse_date(match.group("from"))
        observed_to = _parse_date(match.group("to"))
        effective = _parse_date(match.group("effective"))
        if observed_from != from_period_end or observed_to != to_period_end:
            return "corporate_action_period_mismatch"
        if effective is None or not from_period_end < effective <= to_period_end:
            return "corporate_action_effective_date_invalid"
        try:
            new_shares = Decimal(match.group("new"))
            old_shares = Decimal(match.group("old"))
        except InvalidOperation:
            return "corporate_action_ratio_invalid"
        kind = match.group("kind").casefold()
        if (
            new_shares <= 0
            or old_shares <= 0
            or (kind == "forward" and new_shares <= old_shares)
            or (kind == "reverse" and new_shares >= old_shares)
        ):
            return "corporate_action_ratio_invalid"
        return (
            _format_decimal(new_shares / old_shares),
            "corporate_action_split_verified",
        )
    return "corporate_action_evidence_ambiguous"


def reconcile_corporate_actions(
    *,
    request: PrimarySourceRequest,
    passages: tuple[PrimaryEvidencePassage, ...],
    from_period_end: date,
    to_period_end: date,
) -> CorporateActionAssessment:
    if not passages:
        return _unresolved("corporate_action_evidence_missing")
    if from_period_end >= to_period_end:
        return _unresolved("corporate_action_period_invalid")
    reference_keys = tuple(passage.reference_key for passage in passages)
    if len(reference_keys) != len(set(reference_keys)):
        return _unresolved("corporate_action_evidence_conflict")

    parsed: list[tuple[str, str, str]] = []
    for passage in passages:
        if reason := _source_reason(passage, request.as_of_cutoff):
            return _unresolved(reason)
        result = _parse_factor(
            passage,
            from_period_end=from_period_end,
            to_period_end=to_period_end,
        )
        if isinstance(result, str):
            return _unresolved(result)
        factor, reason = result
        parsed.append((factor, reason, passage.reference_key))

    if len({(factor, reason) for factor, reason, _ in parsed}) != 1:
        return _unresolved("corporate_action_evidence_conflict")
    factor, reason, _ = parsed[0]
    reconciliation = CorporateActionReconciliation(
        security_id=request.security_id,
        cik=request.cik,
        from_period_end=from_period_end,
        to_period_end=to_period_end,
        state="verified",
        prior_to_current_factor=factor,
        evidence_reference_keys=tuple(reference_keys),
    )
    return CorporateActionAssessment(
        policy_version=CORPORATE_ACTION_POLICY_VERSION,
        state="verified",
        reason_codes=(reason,),
        reconciliation=reconciliation,
    )


__all__ = [
    "CORPORATE_ACTION_POLICY_VERSION",
    "CorporateActionAssessment",
    "reconcile_corporate_actions",
]
