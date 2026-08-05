from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
import hashlib
import json
import re
from typing import Callable, Mapping, Protocol
from urllib.parse import urlencode

from workers.primary_sources.models import PrimarySourceRequest
from workers.primary_sources.temporal import (
    PublicationTimeAssessment,
    assess_publication_time,
)

from .models import ClinicalTrialSearchIdentity


_NCT_ID_PATTERN = re.compile(r"^NCT[0-9]{8}$")
_POLICY_VERSION = "clinical-trials-source-v2"
_MAX_PAGES = 20
_MAX_HISTORY_CHANGES = 1000
_MAX_HISTORY_FETCHES = 20


class ClinicalTrialsCollectorError(RuntimeError):
    """Raised when ClinicalTrials.gov data cannot be trusted."""


@dataclass(frozen=True, slots=True)
class ClinicalTrialsSettings:
    base_url: str = "https://clinicaltrials.gov"
    page_size: int = 100

    def __post_init__(self) -> None:
        if self.base_url.rstrip("/") != "https://clinicaltrials.gov":
            raise ValueError("ClinicalTrials.gov base URL is unsupported")
        if not 1 <= self.page_size <= 100:
            raise ValueError("ClinicalTrials.gov page size must be 1-100")


@dataclass(frozen=True, slots=True)
class ClinicalTrialsTransportResponse:
    body: bytes
    status: int
    headers: Mapping[str, str]
    final_url: str


class ClinicalTrialsTransport(Protocol):
    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> ClinicalTrialsTransportResponse: ...


@dataclass(frozen=True, slots=True)
class ClinicalTrialIntervention:
    intervention_type: str
    name: str


@dataclass(frozen=True, slots=True)
class ClinicalTrialSponsor:
    name: str
    agency_class: str


@dataclass(frozen=True, slots=True)
class ClinicalTrialStudy:
    nct_id: str
    program_name: str
    brief_title: str
    official_title: str | None
    status: str
    phases: tuple[str, ...]
    interventions: tuple[ClinicalTrialIntervention, ...]
    sponsor: ClinicalTrialSponsor
    start_date: str | None
    primary_completion_date: str | None
    completion_date: str | None
    first_post_date_raw: str | None
    last_update_post_date_raw: str | None
    publication_state: str
    publication_reason_code: str
    update_state: str
    update_reason_code: str
    program_associated: bool
    issuer_associated: bool
    association_reason_code: str
    valid_at_cutoff: bool
    source_class: str
    source_locator: str
    retrieved_at: datetime
    source_payload: str
    content_sha256: str
    history_version_index: int | None = None
    version_source_url: str | None = None
    canonical_url: str | None = None


@dataclass(frozen=True, slots=True)
class ClinicalTrialsSourcePage:
    source_url: str
    retrieved_at: datetime
    source_payload: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ClinicalTrialsCoverageResult:
    requirement_id: str
    policy_version: str
    status: str
    reason_codes: tuple[str, ...]
    included_nct_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClinicalTrialsSnapshot:
    operator_id: str
    security_id: str
    cik: str
    issuer_name: str
    program_name: str
    search_terms: tuple[str, ...]
    allowed_sponsor_names: tuple[str, ...]
    as_of_cutoff: datetime
    policy_version: str
    pages: tuple[ClinicalTrialsSourcePage, ...]
    included_studies: tuple[ClinicalTrialStudy, ...]
    excluded_studies: tuple[ClinicalTrialStudy, ...]
    coverage: ClinicalTrialsCoverageResult


class ClinicalTrialsCollector:
    def __init__(
        self,
        settings: ClinicalTrialsSettings,
        *,
        transport: ClinicalTrialsTransport,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(UTC))

    def collect(
        self,
        request: PrimarySourceRequest,
        search: ClinicalTrialSearchIdentity,
    ) -> ClinicalTrialsSnapshot:
        query = " OR ".join(f'"{term}"' for term in search.search_terms)
        base_source_url = (
            f"{self.settings.base_url.rstrip('/')}/api/v2/studies?"
            + urlencode(
                {
                    "format": "json",
                    "pageSize": self.settings.page_size,
                    "countTotal": "true",
                    "query.term": query,
                }
            )
        )
        pages: list[ClinicalTrialsSourcePage] = []
        studies_payload: list[tuple[object, datetime]] = []
        next_page_token: str | None = None
        seen_tokens: set[str] = set()
        total_count: int | None = None
        for _ in range(_MAX_PAGES):
            source_url = base_source_url
            if next_page_token is not None:
                source_url += "&" + urlencode(
                    {"pageToken": next_page_token}
                )
            response = self.transport.request(
                source_url,
                headers={"Accept": "application/json"},
            )
            payload, source_payload = self._response_payload(
                response,
                expected_url=source_url,
            )
            page_studies = payload.get("studies")
            if not isinstance(page_studies, list):
                raise ClinicalTrialsCollectorError(
                    "ClinicalTrials.gov studies are invalid"
                )
            page_total_count = payload.get("totalCount")
            if (
                isinstance(page_total_count, bool)
                or not isinstance(page_total_count, int)
                or page_total_count < 0
            ):
                raise ClinicalTrialsCollectorError(
                    "ClinicalTrials.gov total count is invalid"
                )
            if total_count is None:
                total_count = page_total_count
            elif total_count != page_total_count:
                raise ClinicalTrialsCollectorError(
                    "ClinicalTrials.gov total count changed during collection"
                )
            retrieved_at = self._retrieved_at()
            studies_payload.extend(
                (study_payload, retrieved_at)
                for study_payload in page_studies
            )
            pages.append(
                ClinicalTrialsSourcePage(
                    source_url=source_url,
                    retrieved_at=retrieved_at,
                    source_payload=source_payload,
                    content_sha256=hashlib.sha256(response.body).hexdigest(),
                )
            )
            token = payload.get("nextPageToken")
            if token is None:
                break
            if not isinstance(token, str) or not token.strip():
                raise ClinicalTrialsCollectorError(
                    "ClinicalTrials.gov next page token is invalid"
                )
            if token in seen_tokens:
                raise ClinicalTrialsCollectorError(
                    "ClinicalTrials.gov next page token repeated"
                )
            seen_tokens.add(token)
            next_page_token = token
        else:
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov page limit exceeded"
            )
        current_studies = self._deduplicate(
            tuple(
                self._study(
                    item,
                    program_name=search.program_name,
                    search_terms=search.search_terms,
                    issuer_name=request.issuer_name,
                    allowed_sponsor_names=search.allowed_sponsor_names,
                    as_of_cutoff=request.as_of_cutoff,
                    retrieved_at=retrieved_at,
                )
                for item, retrieved_at in studies_payload
            )
        )
        studies = tuple(
            self._historical_study_at_cutoff(
                study,
                program_name=search.program_name,
                search_terms=search.search_terms,
                issuer_name=request.issuer_name,
                allowed_sponsor_names=search.allowed_sponsor_names,
                as_of_cutoff=request.as_of_cutoff,
            )
            for study in current_studies
        )
        if total_count != len(current_studies):
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov total count mismatch"
            )
        included = tuple(study for study in studies if study.valid_at_cutoff)
        excluded = tuple(study for study in studies if not study.valid_at_cutoff)
        indeterminate = any(
            study.publication_state
            in {"date_only_ambiguous", "timezone_ambiguous", "unavailable"}
            or study.update_state
            in {"date_only_ambiguous", "timezone_ambiguous", "unavailable"}
            for study in excluded
        )
        association_missing = any(
            (not study.program_associated or not study.issuer_associated)
            and study.publication_state in {"date_only", "exact"}
            and study.update_state in {"date_only", "exact"}
            for study in excluded
        )
        coverage = ClinicalTrialsCoverageResult(
            requirement_id="clinical_trials_primary_source",
            policy_version=_POLICY_VERSION,
            status=(
                "indeterminate"
                if indeterminate
                else "covered"
                if included
                else "not_covered"
            ),
            reason_codes=(
                ("clinical_trials_temporal_metadata_indeterminate",)
                if indeterminate
                else (
                    ("clinical_trials_source_covered",)
                    if included
                    else (
                        ("clinical_trials_program_association_missing",)
                        if association_missing
                        else (
                            (
                                "clinical_trials_no_version_valid_at_cutoff",
                            )
                            if any(
                                study.update_reason_code
                                == "clinical_trial_no_version_valid_at_cutoff"
                                for study in excluded
                            )
                            else ("clinical_trials_no_study_valid_at_cutoff",)
                        )
                        if excluded
                        else ("clinical_trials_no_matching_study",)
                    )
                )
            ),
            included_nct_ids=tuple(study.nct_id for study in included),
        )
        return ClinicalTrialsSnapshot(
            operator_id=request.operator_id,
            security_id=request.security_id,
            cik=request.cik,
            issuer_name=request.issuer_name,
            program_name=search.program_name,
            search_terms=search.search_terms,
            allowed_sponsor_names=search.allowed_sponsor_names,
            as_of_cutoff=request.as_of_cutoff,
            policy_version=_POLICY_VERSION,
            pages=tuple(pages),
            included_studies=included,
            excluded_studies=excluded,
            coverage=coverage,
        )

    def _historical_study_at_cutoff(
        self,
        current: ClinicalTrialStudy,
        *,
        program_name: str,
        search_terms: tuple[str, ...],
        issuer_name: str,
        allowed_sponsor_names: tuple[str, ...],
        as_of_cutoff: datetime,
    ) -> ClinicalTrialStudy:
        if (
            current.publication_state == "after_cutoff"
            or current.update_state != "after_cutoff"
        ):
            return current
        summary_url = (
            f"{self.settings.base_url.rstrip('/')}/api/int/studies/"
            f"{current.nct_id}?history=true"
        )
        summary_response = self.transport.request(
            summary_url,
            headers={"Accept": "application/json"},
        )
        summary, _summary_payload = self._response_payload(
            summary_response,
            expected_url=summary_url,
        )
        summary_study = _mapping(summary, "study")
        if _study_nct_id(summary_study) != current.nct_id:
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov history summary identity mismatch"
            )
        history = _mapping(summary, "history")
        changes = history.get("changes")
        if not isinstance(changes, list) or len(changes) > _MAX_HISTORY_CHANGES:
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov history changes are invalid"
            )
        candidates: list[tuple[date, int]] = []
        seen_versions: set[int] = set()
        for change in changes:
            if not isinstance(change, dict):
                raise ClinicalTrialsCollectorError(
                    "ClinicalTrials.gov history change is invalid"
                )
            version = change.get("version")
            if (
                isinstance(version, bool)
                or not isinstance(version, int)
                or version < 0
                or version in seen_versions
            ):
                raise ClinicalTrialsCollectorError(
                    "ClinicalTrials.gov history version is invalid"
                )
            seen_versions.add(version)
            review_not_passed = change.get("reviewNotPassed", False)
            if not isinstance(review_not_passed, bool):
                raise ClinicalTrialsCollectorError(
                    "ClinicalTrials.gov history review state is invalid"
                )
            submitted_raw = change.get("date")
            if not isinstance(submitted_raw, str):
                raise ClinicalTrialsCollectorError(
                    "ClinicalTrials.gov history date is invalid"
                )
            try:
                submitted_date = date.fromisoformat(submitted_raw)
            except ValueError as error:
                raise ClinicalTrialsCollectorError(
                    "ClinicalTrials.gov history date is invalid"
                ) from error
            if (
                not review_not_passed
                and submitted_date <= as_of_cutoff.astimezone(UTC).date()
            ):
                candidates.append((submitted_date, version))
        candidates.sort(reverse=True)
        for _submitted_date, version in candidates[:_MAX_HISTORY_FETCHES]:
            version_url = (
                f"{self.settings.base_url.rstrip('/')}/api/int/studies/"
                f"{current.nct_id}/history/{version}"
            )
            version_response = self.transport.request(
                version_url,
                headers={"Accept": "application/json"},
            )
            wrapper, _version_payload = self._response_payload(
                version_response,
                expected_url=version_url,
            )
            if wrapper.get("studyVersion") != version:
                raise ClinicalTrialsCollectorError(
                    "ClinicalTrials.gov history version identity mismatch"
                )
            historical_payload = _mapping(wrapper, "study")
            if _study_nct_id(historical_payload) != current.nct_id:
                raise ClinicalTrialsCollectorError(
                    "ClinicalTrials.gov history study identity mismatch"
                )
            historical = self._study(
                historical_payload,
                program_name=program_name,
                search_terms=search_terms,
                issuer_name=issuer_name,
                allowed_sponsor_names=allowed_sponsor_names,
                as_of_cutoff=as_of_cutoff,
                retrieved_at=self._retrieved_at(),
                evidence_payload=wrapper,
                source_locator=version_url,
                history_version_index=version,
            )
            if (
                historical.publication_state != "after_cutoff"
                and historical.update_state not in {
                    "after_cutoff",
                    "date_only_ambiguous",
                    "timezone_ambiguous",
                    "unavailable",
                }
            ):
                return historical
        return replace(
            current,
            update_reason_code="clinical_trial_no_version_valid_at_cutoff",
        )

    @staticmethod
    def _response_payload(
        response: ClinicalTrialsTransportResponse,
        *,
        expected_url: str,
    ) -> tuple[Mapping[str, object], str]:
        if not 200 <= response.status < 300:
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov returned HTTP "
                f"{response.status} for studies request"
            )
        if response.final_url != expected_url:
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov studies response redirected"
            )
        media_type = _header(response.headers, "content-type").partition(";")[
            0
        ].strip().lower()
        if media_type != "application/json":
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov content type is invalid"
            )
        try:
            source_payload = response.body.decode("utf-8")
            payload = json.loads(source_payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov response is invalid JSON"
            ) from error
        if not isinstance(payload, dict):
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov response is invalid"
            )
        return payload, source_payload

    def _study(
        self,
        payload: object,
        *,
        program_name: str,
        search_terms: tuple[str, ...],
        issuer_name: str,
        allowed_sponsor_names: tuple[str, ...],
        as_of_cutoff: datetime,
        retrieved_at: datetime,
        evidence_payload: object | None = None,
        source_locator: str | None = None,
        history_version_index: int | None = None,
    ) -> ClinicalTrialStudy:
        if not isinstance(payload, dict):
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov study is invalid"
            )
        protocol = _mapping(payload, "protocolSection")
        identity = _mapping(protocol, "identificationModule")
        status_module = _mapping(protocol, "statusModule")
        design = _mapping(protocol, "designModule")
        intervention_module = _mapping(protocol, "armsInterventionsModule")
        sponsor_module = _mapping(protocol, "sponsorCollaboratorsModule")
        nct_id = _required_string(identity, "nctId")
        if _NCT_ID_PATTERN.fullmatch(nct_id) is None:
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov NCT ID is invalid"
            )
        first_post = _temporal_date_value(
            status_module,
            "studyFirstPostDateStruct",
        )
        last_update = _temporal_date_value(
            status_module,
            "lastUpdatePostDateStruct",
        )
        publication = _assess_registry_time(
            first_post,
            as_of_cutoff,
            field_name="publication",
        )
        update = _assess_registry_time(
            last_update,
            as_of_cutoff,
            field_name="update",
        )
        phases_payload = design.get("phases", [])
        if not isinstance(phases_payload, list) or any(
            not isinstance(item, str) or not item.strip()
            for item in phases_payload
        ):
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov study phases are invalid"
            )
        interventions_payload = intervention_module.get("interventions", [])
        if not isinstance(interventions_payload, list):
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov interventions are invalid"
            )
        if any(not isinstance(item, dict) for item in interventions_payload):
            raise ClinicalTrialsCollectorError(
                "ClinicalTrials.gov intervention is invalid"
            )
        interventions = tuple(
            ClinicalTrialIntervention(
                intervention_type=_required_string(item, "type"),
                name=_required_string(item, "name"),
            )
            for item in interventions_payload
        )
        lead_sponsor = _mapping(sponsor_module, "leadSponsor")
        normalized_payload = json.dumps(
            payload if evidence_payload is None else evidence_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        brief_title = _required_string(identity, "briefTitle")
        official_title = _optional_string(identity, "officialTitle")
        normalized_terms = {_normalized_name(term) for term in search_terms}
        program_associated = any(
            _normalized_name(intervention.name) in normalized_terms
            for intervention in interventions
        )
        sponsor_name = _required_string(lead_sponsor, "name")
        permitted_sponsors = {
            _normalized_organization_name(issuer_name),
            *(
                _normalized_organization_name(name)
                for name in allowed_sponsor_names
            ),
        }
        issuer_associated = (
            _normalized_organization_name(sponsor_name)
            in permitted_sponsors
        )
        return ClinicalTrialStudy(
            nct_id=nct_id,
            program_name=program_name,
            brief_title=brief_title,
            official_title=official_title,
            status=_required_string(status_module, "overallStatus"),
            phases=tuple(phases_payload),
            interventions=interventions,
            sponsor=ClinicalTrialSponsor(
                name=sponsor_name,
                agency_class=_required_string(lead_sponsor, "class"),
            ),
            start_date=_optional_date_value(status_module, "startDateStruct"),
            primary_completion_date=_optional_date_value(
                status_module,
                "primaryCompletionDateStruct",
            ),
            completion_date=_optional_date_value(
                status_module,
                "completionDateStruct",
            ),
            first_post_date_raw=first_post,
            last_update_post_date_raw=last_update,
            publication_state=publication.state,
            publication_reason_code=publication.reason_code,
            update_state=update.state,
            update_reason_code=update.reason_code,
            program_associated=program_associated,
            issuer_associated=issuer_associated,
            association_reason_code=(
                "clinical_trial_program_association_verified"
                if program_associated and issuer_associated
                else (
                    "clinical_trial_program_alias_missing"
                    if not program_associated
                    else "clinical_trial_issuer_association_missing"
                )
            ),
            valid_at_cutoff=(
                publication.valid_at_cutoff
                and update.valid_at_cutoff
                and program_associated
                and issuer_associated
            ),
            source_class="clinical_trial_registry",
            source_locator=(
                source_locator
                if source_locator is not None
                else f"https://clinicaltrials.gov/study/{nct_id}"
            ),
            retrieved_at=retrieved_at,
            source_payload=normalized_payload,
            content_sha256=hashlib.sha256(
                normalized_payload.encode("utf-8")
            ).hexdigest(),
            history_version_index=history_version_index,
            version_source_url=source_locator,
            canonical_url=f"https://clinicaltrials.gov/study/{nct_id}",
        )

    def _retrieved_at(self) -> datetime:
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise RuntimeError(
                "ClinicalTrials.gov collector clock must include timezone"
            )
        return retrieved_at.astimezone(UTC)

    @staticmethod
    def _deduplicate(
        studies: tuple[ClinicalTrialStudy, ...],
    ) -> tuple[ClinicalTrialStudy, ...]:
        by_id: dict[str, ClinicalTrialStudy] = {}
        for study in studies:
            existing = by_id.get(study.nct_id)
            if (
                existing is not None
                and existing.content_sha256 != study.content_sha256
            ):
                raise ClinicalTrialsCollectorError(
                    "ClinicalTrials.gov study identity conflict"
                )
            if existing is None:
                by_id[study.nct_id] = study
        return tuple(by_id[nct_id] for nct_id in sorted(by_id))


def _header(headers: Mapping[str, str], name: str) -> str:
    return next(
        (
            value
            for key, value in headers.items()
            if key.lower() == name.lower()
        ),
        "",
    )


def _normalized_name(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _normalized_organization_name(value: str) -> str:
    words = _normalized_name(value).split()
    legal_suffixes = {
        "co",
        "company",
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "limited",
        "llc",
        "ltd",
        "plc",
    }
    while words and words[-1] in legal_suffixes:
        words.pop()
    return " ".join(words)


def _mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ClinicalTrialsCollectorError(
            f"ClinicalTrials.gov {key} is invalid"
        )
    return value


def _study_nct_id(payload: Mapping[str, object]) -> str:
    protocol = _mapping(payload, "protocolSection")
    identity = _mapping(protocol, "identificationModule")
    nct_id = _required_string(identity, "nctId")
    if _NCT_ID_PATTERN.fullmatch(nct_id) is None:
        raise ClinicalTrialsCollectorError(
            "ClinicalTrials.gov NCT ID is invalid"
        )
    return nct_id


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ClinicalTrialsCollectorError(
            f"ClinicalTrials.gov {key} is invalid"
        )
    return value.strip()


def _optional_string(
    payload: Mapping[str, object],
    key: str,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ClinicalTrialsCollectorError(
            f"ClinicalTrials.gov {key} is invalid"
        )
    return value.strip()


def _temporal_date_value(
    payload: Mapping[str, object],
    key: str,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ClinicalTrialsCollectorError(
            f"ClinicalTrials.gov {key} is invalid"
        )
    raw_date = value.get("date")
    if raw_date is None:
        return None
    if not isinstance(raw_date, str) or not raw_date.strip():
        raise ClinicalTrialsCollectorError(
            f"ClinicalTrials.gov {key} date is invalid"
        )
    return raw_date.strip()


def _optional_date_value(
    payload: Mapping[str, object],
    key: str,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ClinicalTrialsCollectorError(
            f"ClinicalTrials.gov {key} is invalid"
        )
    return _required_string(value, "date")


def _assess_registry_time(
    value: object,
    as_of_cutoff: datetime,
    *,
    field_name: str,
) -> PublicationTimeAssessment:
    assessment = assess_publication_time(value, as_of_cutoff)
    if assessment.state == "date_only":
        assert assessment.publication_date is not None
        cutoff_date = as_of_cutoff.astimezone(UTC).date()
        if assessment.publication_date > cutoff_date:
            return PublicationTimeAssessment(
                state="after_cutoff",
                reason_code=f"{field_name}_after_cutoff",
                valid_at_cutoff=False,
                published_at=None,
                publication_date=assessment.publication_date,
            )
        if not assessment.valid_at_cutoff:
            return PublicationTimeAssessment(
                state="date_only_ambiguous",
                reason_code=(
                    f"{field_name}_date_only_ambiguous_at_cutoff"
                ),
                valid_at_cutoff=False,
                published_at=None,
                publication_date=assessment.publication_date,
            )
        return PublicationTimeAssessment(
            state="date_only",
            reason_code=f"{field_name}_date_only_before_cutoff",
            valid_at_cutoff=True,
            published_at=None,
            publication_date=assessment.publication_date,
        )
    reason_by_state = {
        "exact": f"{field_name}_time_verified_at_cutoff",
        "after_cutoff": f"{field_name}_after_cutoff",
        "timezone_ambiguous": f"{field_name}_timezone_unresolved",
        "unavailable": f"{field_name}_time_unavailable",
    }
    return PublicationTimeAssessment(
        state=assessment.state,
        reason_code=reason_by_state[assessment.state],
        valid_at_cutoff=assessment.valid_at_cutoff,
        published_at=assessment.published_at,
        publication_date=assessment.publication_date,
    )


def clinical_trials_pipeline_inputs(
    snapshot: ClinicalTrialsSnapshot,
):
    from workers.primary_sources.pipeline import PrimaryEvidencePassage

    coverage_keys = (
        frozenset({"authoritative_trial"})
        if snapshot.coverage.status == "covered"
        else frozenset()
    )
    passages: list[PrimaryEvidencePassage] = []
    for study in snapshot.included_studies:
        update = assess_publication_time(
            study.last_update_post_date_raw,
            snapshot.as_of_cutoff,
        )
        if not update.valid_at_cutoff:
            raise ClinicalTrialsCollectorError(
                "included ClinicalTrials.gov study is invalid at cutoff"
            )
        if update.published_at is not None:
            available_at = update.published_at
        elif update.publication_date is not None:
            available_at = datetime.combine(
                update.publication_date,
                time.max,
                tzinfo=UTC,
            )
        else:
            raise ClinicalTrialsCollectorError(
                "included ClinicalTrials.gov study availability is unavailable"
            )
        passages.append(
            PrimaryEvidencePassage(
                reference_key=f"clinical-trial:{study.nct_id}",
                source_class="clinical",
                coverage_keys=coverage_keys,
                source_locator=study.source_locator,
                canonical_url=(
                    study.canonical_url
                    or f"https://clinicaltrials.gov/study/{study.nct_id}"
                ),
                publication_at=update.published_at,
                retrieved_at=study.retrieved_at,
                effective_at=None,
                filing_period_start=None,
                filing_period_end=None,
                document_content_hash=study.content_sha256,
                passage_text=study.source_payload,
                freshness="current",
                origin_policy_version="clinical-trials-origin-v1",
                available_at=available_at,
            )
        )
    return tuple(passages)


def clinical_trials_coverage_proof(
    snapshot: ClinicalTrialsSnapshot,
):
    from workers.primary_sources.pipeline import PrimarySourceCoverageProof

    state_by_status = {
        "covered": "complete",
        "not_covered": "incomplete",
        "indeterminate": "indeterminate",
    }
    try:
        state = state_by_status[snapshot.coverage.status]
    except KeyError as error:
        raise ClinicalTrialsCollectorError(
            "ClinicalTrials.gov coverage status is invalid"
        ) from error
    return PrimarySourceCoverageProof(
        requirement_id="authoritative_trial",
        source_class="clinical",
        policy_version=snapshot.policy_version,
        state=state,
        reason_codes=snapshot.coverage.reason_codes,
        evidence_reference_keys=tuple(
            f"clinical-trial:{study.nct_id}"
            for study in snapshot.included_studies
        ),
    )


__all__ = [
    "ClinicalTrialIntervention",
    "ClinicalTrialSponsor",
    "ClinicalTrialStudy",
    "ClinicalTrialsCollector",
    "ClinicalTrialsCollectorError",
    "ClinicalTrialsCoverageResult",
    "ClinicalTrialsSettings",
    "ClinicalTrialsSnapshot",
    "ClinicalTrialsSourcePage",
    "ClinicalTrialsTransport",
    "ClinicalTrialsTransportResponse",
    "clinical_trials_coverage_proof",
    "clinical_trials_pipeline_inputs",
]
