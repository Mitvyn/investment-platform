from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
import json
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from investment_research_os.research_runs import (
    DEFAULT_WORKFLOW_CONFIG_REGISTRY,
    ResearchRun,
    WorkflowConfigRegistry,
)
from workers.clinical_trials.models import ClinicalTrialSearchIdentity
from workers.official_sources.models import (
    OfficialPassageSpec,
    OfficialSourceLocator,
)
from workers.sec.collector import ACCESSION_PATTERN
from workers.sec.documents import (
    SecFilingDocument,
    SecFilingDocumentSnapshot,
)

from .models import PrimarySourceRequest


PRIMARY_SOURCE_PLAN_V1 = "primary_source_plan.v1"
PRIMARY_SOURCE_PLAN_V2 = "primary_source_plan.v2"
PRIMARY_SOURCE_PLAN_V3 = "primary_source_plan.v3"
PRIMARY_SOURCE_PLAN_VERSION = PRIMARY_SOURCE_PLAN_V2
_SUPPORTED_PLAN_VERSIONS = frozenset(
    {
        PRIMARY_SOURCE_PLAN_V1,
        PRIMARY_SOURCE_PLAN_V2,
        PRIMARY_SOURCE_PLAN_V3,
    }
)
_MAX_PLAN_BYTES = 256 * 1024
_MAX_V2_SEC_PASSAGES = 32
_PLAN_FIELDS = frozenset(
    {
        "contract_version",
        "plan_id",
        "revision",
        "effective_at",
        "question_type",
        "workflow_config_version",
        "security",
        "sec_passages",
        "issuer_sources",
        "clinical_trial_search",
        "regulatory_sources",
    }
)
_SECURITY_FIELDS = frozenset(
    {
        "security_id",
        "cik",
        "issuer_name",
        "primary_listing_exchange",
    }
)
_SEC_PASSAGE_FIELDS_V1 = frozenset(
    {"reference_key", "role", "selected_form", "exact_text"}
)
_SEC_PASSAGE_FIELDS_V2 = frozenset(
    {*_SEC_PASSAGE_FIELDS_V1, "selected_accession_number"}
)
_LOCATOR_FIELDS = frozenset(
    {
        "source_key",
        "requirement_id",
        "title",
        "source_url",
        "publication_time",
        "effective_date",
        "coverage_role",
        "coverage_mode",
        "passages",
    }
)
_PASSAGE_FIELDS = frozenset({"passage_key", "locator", "exact_text"})
_CLINICAL_FIELDS = frozenset(
    {"program_name", "search_terms", "allowed_sponsor_names"}
)
_CORE_SEC_PASSAGE_ROLES = frozenset(
    {"required_filing", "identity_listing", "financing"}
)
_SEC_PASSAGE_ROLES_V3 = frozenset(
    {*_CORE_SEC_PASSAGE_ROLES, "corporate_action"}
)
_SEC_FORMS_V1 = frozenset({"10-K", "10-Q", "8-K"})
_SEC_FORMS_V2 = frozenset(
    {
        *_SEC_FORMS_V1,
        "S-3",
        "S-3/A",
        "S-3ASR",
        "424B3",
        "424B5",
    }
)
_REGULATORY_HOSTS = frozenset(
    {
        "accessdata.fda.gov",
        "fda.gov",
        "precision.fda.gov",
        "www.accessdata.fda.gov",
        "www.fda.gov",
    }
)


class PrimarySourcePlanError(ValueError):
    """Raised when a source plan cannot be loaded or bound safely."""


@dataclass(frozen=True, slots=True)
class SecPassagePlan:
    reference_key: str
    role: str
    selected_form: str
    selected_accession_number: str | None
    exact_text: str


@dataclass(frozen=True, slots=True)
class LoadedPrimarySourcePlan:
    contract_version: str
    plan_id: str
    revision: int
    effective_at: datetime
    question_type: str
    workflow_config_version: str
    question_type_version: str
    thesis_contract_id: str
    eligibility_policy_version: str
    security_id: str
    cik: str
    issuer_name: str
    primary_listing_exchange: str
    sec_passages: tuple[SecPassagePlan, ...]
    issuer_sources: tuple[OfficialSourceLocator, ...]
    clinical_trial_search: ClinicalTrialSearchIdentity
    regulatory_sources: tuple[OfficialSourceLocator, ...]
    content_hash: str


@dataclass(frozen=True, slots=True)
class PrimarySourcePlan:
    loaded: LoadedPrimarySourcePlan
    operator_id: str
    as_of_cutoff: datetime
    trusted_issuer_hosts: tuple[str, ...]

    @property
    def sec_passages(self) -> tuple[SecPassagePlan, ...]:
        return self.loaded.sec_passages

    @property
    def issuer_sources(self) -> tuple[OfficialSourceLocator, ...]:
        return self.loaded.issuer_sources

    @property
    def clinical_trial_search(self) -> ClinicalTrialSearchIdentity:
        return self.loaded.clinical_trial_search

    @property
    def regulatory_sources(self) -> tuple[OfficialSourceLocator, ...]:
        return self.loaded.regulatory_sources

    @property
    def content_hash(self) -> str:
        return self.loaded.content_hash

    @property
    def regulatory_allowed_hosts(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    cast(str, urlsplit(source.source_url).hostname).casefold()
                    for source in self.regulatory_sources
                }
            )
        )


@dataclass(frozen=True, slots=True)
class ResolvedSecPassageSource:
    plan: SecPassagePlan
    document: SecFilingDocument


@dataclass(frozen=True, slots=True)
class PrimarySourcePlanRunBinding:
    operator_id: str
    research_run_id: str
    security_id: str
    as_of_cutoff: datetime
    question_type: str
    workflow_config_version: str
    plan_id: str
    plan_revision: int
    plan_content_hash: str


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PrimarySourcePlanError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise PrimarySourcePlanError(f"{label} fields are invalid")
    return value


def _fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    label: str,
) -> None:
    if frozenset(value) != expected:
        raise PrimarySourcePlanError(f"{label} fields are invalid")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PrimarySourcePlanError(f"{label} is required")
    return value.strip()


def _sequence(value: object, label: str) -> Sequence[object]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        raise PrimarySourcePlanError(f"{label} must be a list")
    if not value:
        raise PrimarySourcePlanError(f"{label} must not be empty")
    return value


def _text_tuple(value: object, label: str) -> tuple[str, ...]:
    values = tuple(_text(item, label) for item in _sequence(value, label))
    if len(values) != len(set(values)):
        raise PrimarySourcePlanError(f"{label} must be unique")
    return values


def _optional_text_tuple(value: object, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        raise PrimarySourcePlanError(f"{label} must be a list")
    values = tuple(_text(item, label) for item in value)
    if len(values) != len(set(values)):
        raise PrimarySourcePlanError(f"{label} must be unique")
    return values


def _date(value: object, label: str) -> date | None:
    if value is None:
        return None
    text = _text(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise PrimarySourcePlanError(f"{label} is invalid") from error
    if parsed.isoformat() != text:
        raise PrimarySourcePlanError(f"{label} is invalid")
    return parsed


def _timestamp(value: object, label: str) -> datetime:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise PrimarySourcePlanError(f"{label} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PrimarySourcePlanError(f"{label} must include timezone")
    return parsed.astimezone(UTC)


def _uuid(value: object, label: str) -> str:
    text = _text(value, label)
    try:
        return str(UUID(text))
    except ValueError as error:
        raise PrimarySourcePlanError(f"{label} must be a UUID") from error


def _https_host(value: str, label: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise PrimarySourcePlanError(f"{label} origin is invalid") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        raise PrimarySourcePlanError(f"{label} origin is invalid")
    return parsed.hostname.casefold()


def _passage(value: object) -> OfficialPassageSpec:
    mapping = _mapping(value, "source passage")
    _fields(mapping, _PASSAGE_FIELDS, "source passage")
    try:
        return OfficialPassageSpec(
            passage_key=_text(mapping["passage_key"], "passage key"),
            locator=_text(mapping["locator"], "passage locator"),
            exact_text=_text(mapping["exact_text"], "exact passage text"),
        )
    except ValueError as error:
        raise PrimarySourcePlanError(str(error)) from error


def _locator(
    value: object,
    *,
    lane: str,
) -> OfficialSourceLocator:
    mapping = _mapping(value, f"{lane} source")
    _fields(mapping, _LOCATOR_FIELDS, f"{lane} source")
    source_url = _text(mapping["source_url"], f"{lane} source URL")
    host = _https_host(source_url, f"{lane} source")
    if lane == "regulatory" and host not in _REGULATORY_HOSTS:
        raise PrimarySourcePlanError("regulatory source origin is invalid")
    requirement_id = _text(
        mapping["requirement_id"],
        f"{lane} source requirement",
    )
    expected_requirement = {
        "issuer": "issuer_pipeline",
        "regulatory": "us_regulatory",
    }[lane]
    if requirement_id != expected_requirement:
        raise PrimarySourcePlanError(f"{lane} source requirement is invalid")
    passages = tuple(
        sorted(
            (_passage(item) for item in _sequence(mapping["passages"], "passages")),
            key=lambda passage: passage.passage_key,
        )
    )
    try:
        return OfficialSourceLocator(
            source_key=_text(mapping["source_key"], "source key"),
            requirement_id=requirement_id,
            title=_text(mapping["title"], "source title"),
            source_url=source_url,
            publication_time=_text(
                mapping["publication_time"],
                "source publication time",
            ),
            effective_date=_date(
                mapping["effective_date"],
                "source effective date",
            ),
            coverage_role=_text(mapping["coverage_role"], "coverage role"),
            coverage_mode=_text(mapping["coverage_mode"], "coverage mode"),
            passages=passages,
        )
    except ValueError as error:
        raise PrimarySourcePlanError(str(error)) from error


def _locators(
    value: object,
    *,
    lane: str,
) -> tuple[OfficialSourceLocator, ...]:
    locators = tuple(
        sorted(
            (
                _locator(item, lane=lane)
                for item in _sequence(value, f"{lane} sources")
            ),
            key=lambda locator: (
                locator.requirement_id,
                locator.source_key,
                locator.source_url,
            ),
        )
    )
    source_keys = tuple(locator.source_key for locator in locators)
    if len(source_keys) != len(set(source_keys)):
        raise PrimarySourcePlanError(f"{lane} source keys must be unique")
    coverage_modes = {locator.coverage_mode for locator in locators}
    if len(coverage_modes) != 1:
        raise PrimarySourcePlanError(
            f"{lane} source coverage modes must agree"
        )
    if not any(locator.coverage_role == "required" for locator in locators):
        raise PrimarySourcePlanError(
            f"{lane} sources need at least one required locator"
        )
    return locators


def _sec_passage(
    value: object,
    *,
    contract_version: str,
) -> SecPassagePlan:
    mapping = _mapping(value, "SEC passage plan")
    fields = frozenset(mapping)
    if contract_version == PRIMARY_SOURCE_PLAN_V1:
        if fields != _SEC_PASSAGE_FIELDS_V1:
            raise PrimarySourcePlanError(
                "SEC passage plan fields are invalid"
            )
    elif contract_version in {PRIMARY_SOURCE_PLAN_V2, PRIMARY_SOURCE_PLAN_V3}:
        if fields not in {
            _SEC_PASSAGE_FIELDS_V1,
            _SEC_PASSAGE_FIELDS_V2,
        }:
            raise PrimarySourcePlanError(
                "SEC passage plan fields are invalid"
            )
    else:
        raise PrimarySourcePlanError(
            "source plan version is unsupported"
        )
    role = _text(mapping["role"], "SEC passage role")
    selected_form = _text(mapping["selected_form"], "SEC selected form")
    allowed_roles = (
        _SEC_PASSAGE_ROLES_V3
        if contract_version == PRIMARY_SOURCE_PLAN_V3
        else _CORE_SEC_PASSAGE_ROLES
    )
    if role not in allowed_roles:
        raise PrimarySourcePlanError("SEC passage role is invalid")
    allowed_forms = (
        _SEC_FORMS_V1
        if contract_version == PRIMARY_SOURCE_PLAN_V1
        else _SEC_FORMS_V2
    )
    if selected_form not in allowed_forms:
        raise PrimarySourcePlanError("SEC selected form is invalid")
    selected_accession_number = None
    if "selected_accession_number" in mapping:
        selected_accession_number = _text(
            mapping["selected_accession_number"],
            "SEC selected accession number",
        )
        if (
            ACCESSION_PATTERN.fullmatch(
                selected_accession_number
            )
            is None
        ):
            raise PrimarySourcePlanError(
                "SEC selected accession number is invalid"
            )
    if (
        contract_version == PRIMARY_SOURCE_PLAN_V3
        and role == "corporate_action"
        and selected_accession_number is None
    ):
        raise PrimarySourcePlanError(
            "corporate action SEC passage requires selected accession"
        )
    return SecPassagePlan(
        reference_key=_text(
            mapping["reference_key"],
            "SEC passage reference key",
        ),
        role=role,
        selected_form=selected_form,
        selected_accession_number=selected_accession_number,
        exact_text=_text(mapping["exact_text"], "SEC exact passage"),
    )


def _validate_sec_passage_cardinality(
    contract_version: str,
    passages: tuple[SecPassagePlan, ...],
) -> None:
    roles = (
        _SEC_PASSAGE_ROLES_V3
        if contract_version == PRIMARY_SOURCE_PLAN_V3
        else _CORE_SEC_PASSAGE_ROLES
    )
    counts = {
        role: sum(passage.role == role for passage in passages)
        for role in roles
    }
    reference_keys = tuple(
        passage.reference_key for passage in passages
    )
    if len(reference_keys) != len(set(reference_keys)):
        raise PrimarySourcePlanError(
            "SEC passage reference keys must be unique"
        )
    if contract_version == PRIMARY_SOURCE_PLAN_V1:
        if not _CORE_SEC_PASSAGE_ROLES <= {
            passage.role for passage in passages
        }:
            raise PrimarySourcePlanError(
                "SEC passage required roles are missing"
            )
        if (
            len(passages) != len(_CORE_SEC_PASSAGE_ROLES)
            or any(count != 1 for count in counts.values())
        ):
            raise PrimarySourcePlanError(
                "SEC passage roles must appear exactly once"
            )
        return
    if contract_version == PRIMARY_SOURCE_PLAN_V2:
        if (
            len(passages) > _MAX_V2_SEC_PASSAGES
            or counts["required_filing"] != 1
            or counts["identity_listing"] != 1
            or counts["financing"] < 1
            or sum(counts.values()) != len(passages)
        ):
            raise PrimarySourcePlanError(
                "SEC passage v2 cardinality is invalid"
            )
        return
    if contract_version == PRIMARY_SOURCE_PLAN_V3:
        if (
            len(passages) > _MAX_V2_SEC_PASSAGES
            or counts["required_filing"] != 1
            or counts["identity_listing"] != 1
            or counts["financing"] < 1
            or counts["corporate_action"] != 1
            or sum(counts.values()) != len(passages)
        ):
            raise PrimarySourcePlanError(
                "SEC passage v3 cardinality is invalid"
            )
        return
    raise PrimarySourcePlanError("source plan version is unsupported")


def _clinical_search(value: object) -> ClinicalTrialSearchIdentity:
    mapping = _mapping(value, "clinical trial search")
    _fields(mapping, _CLINICAL_FIELDS, "clinical trial search")
    try:
        return ClinicalTrialSearchIdentity(
            program_name=_text(mapping["program_name"], "programme name"),
            search_terms=tuple(
                sorted(
                    _text_tuple(mapping["search_terms"], "search terms"),
                )
            ),
            allowed_sponsor_names=tuple(
                sorted(
                    _optional_text_tuple(
                        mapping["allowed_sponsor_names"],
                        "allowed sponsor names",
                    )
                )
            ),
        )
    except ValueError as error:
        raise PrimarySourcePlanError(str(error)) from error


def _canonical_locator(locator: OfficialSourceLocator) -> dict[str, object]:
    return {
        "source_key": locator.source_key,
        "requirement_id": locator.requirement_id,
        "title": locator.title,
        "source_url": locator.source_url,
        "publication_time": locator.publication_time,
        "effective_date": (
            locator.effective_date.isoformat()
            if locator.effective_date is not None
            else None
        ),
        "coverage_role": locator.coverage_role,
        "coverage_mode": locator.coverage_mode,
        "passages": [
            {
                "passage_key": passage.passage_key,
                "locator": passage.locator,
                "exact_text": passage.exact_text,
            }
            for passage in locator.passages
        ],
    }


def _canonical_sec_passage(
    passage: SecPassagePlan,
    *,
    contract_version: str,
) -> dict[str, object]:
    canonical: dict[str, object] = {
        "reference_key": passage.reference_key,
        "role": passage.role,
        "selected_form": passage.selected_form,
        "exact_text": passage.exact_text,
    }
    if (
        contract_version in {PRIMARY_SOURCE_PLAN_V2, PRIMARY_SOURCE_PLAN_V3}
        and passage.selected_accession_number is not None
    ):
        canonical["selected_accession_number"] = (
            passage.selected_accession_number
        )
    return canonical


def _canonical_payload(
    *,
    contract_version: str,
    plan_id: str,
    revision: int,
    effective_at: datetime,
    question_type: str,
    workflow_config_version: str,
    security_id: str,
    cik: str,
    issuer_name: str,
    primary_listing_exchange: str,
    sec_passages: tuple[SecPassagePlan, ...],
    issuer_sources: tuple[OfficialSourceLocator, ...],
    clinical_search: ClinicalTrialSearchIdentity,
    regulatory_sources: tuple[OfficialSourceLocator, ...],
) -> dict[str, object]:
    return {
        "contract_version": contract_version,
        "plan_id": plan_id,
        "revision": revision,
        "effective_at": effective_at.isoformat(),
        "question_type": question_type,
        "workflow_config_version": workflow_config_version,
        "security": {
            "security_id": security_id,
            "cik": cik,
            "issuer_name": issuer_name,
            "primary_listing_exchange": primary_listing_exchange,
        },
        "sec_passages": [
            _canonical_sec_passage(
                passage,
                contract_version=contract_version,
            )
            for passage in sec_passages
        ],
        "issuer_sources": [
            _canonical_locator(locator) for locator in issuer_sources
        ],
        "clinical_trial_search": {
            "program_name": clinical_search.program_name,
            "search_terms": list(clinical_search.search_terms),
            "allowed_sponsor_names": list(
                clinical_search.allowed_sponsor_names
            ),
        },
        "regulatory_sources": [
            _canonical_locator(locator) for locator in regulatory_sources
        ],
    }


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PrimarySourcePlanError("source plan contains duplicate fields")
        result[key] = value
    return result


def load_primary_source_plan(
    raw: bytes,
    *,
    workflow_registry: WorkflowConfigRegistry = (
        DEFAULT_WORKFLOW_CONFIG_REGISTRY
    ),
) -> LoadedPrimarySourcePlan:
    if not isinstance(raw, bytes):
        raise PrimarySourcePlanError("source plan must be bytes")
    if not raw or len(raw) > _MAX_PLAN_BYTES:
        raise PrimarySourcePlanError("source plan size is invalid")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PrimarySourcePlanError("source plan is not valid UTF-8") from error
    try:
        value = json.loads(text, object_pairs_hook=_strict_object)
    except (json.JSONDecodeError, TypeError) as error:
        raise PrimarySourcePlanError("source plan JSON is invalid") from error
    mapping = _mapping(value, "primary source plan")
    _fields(mapping, _PLAN_FIELDS, "primary source plan")
    contract_version = _text(
        mapping["contract_version"],
        "source plan contract version",
    )
    if contract_version not in _SUPPORTED_PLAN_VERSIONS:
        raise PrimarySourcePlanError("source plan version is unsupported")
    plan_id = _uuid(mapping["plan_id"], "source plan ID")
    revision = mapping["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise PrimarySourcePlanError("source plan revision is invalid")
    effective_at = _timestamp(mapping["effective_at"], "source plan effective time")
    question_type = _text(mapping["question_type"], "question type")
    workflow_config_version = _text(
        mapping["workflow_config_version"],
        "workflow config version",
    )
    workflow = workflow_registry.resolve(
        question_type,
        workflow_config_version,
    )
    if workflow is None or not workflow.active:
        raise PrimarySourcePlanError(
            "source plan workflow is unsupported or inactive"
        )
    security = _mapping(mapping["security"], "source plan security")
    _fields(security, _SECURITY_FIELDS, "source plan security")
    security_id = _uuid(security["security_id"], "security ID")
    cik = _text(security["cik"], "CIK")
    if len(cik) != 10 or not cik.isdigit():
        raise PrimarySourcePlanError("CIK must contain exactly 10 digits")
    issuer_name = _text(security["issuer_name"], "issuer name")
    primary_listing_exchange = _text(
        security["primary_listing_exchange"],
        "primary listing exchange",
    )
    sec_passages = tuple(
        sorted(
            (
                _sec_passage(
                    item,
                    contract_version=contract_version,
                )
                for item in _sequence(mapping["sec_passages"], "SEC passages")
            ),
            key=lambda passage: passage.reference_key,
        )
    )
    _validate_sec_passage_cardinality(contract_version, sec_passages)
    issuer_sources = _locators(mapping["issuer_sources"], lane="issuer")
    regulatory_sources = _locators(
        mapping["regulatory_sources"],
        lane="regulatory",
    )
    clinical_search = _clinical_search(mapping["clinical_trial_search"])
    canonical = _canonical_payload(
        contract_version=contract_version,
        plan_id=plan_id,
        revision=revision,
        effective_at=effective_at,
        question_type=question_type,
        workflow_config_version=workflow_config_version,
        security_id=security_id,
        cik=cik,
        issuer_name=issuer_name,
        primary_listing_exchange=primary_listing_exchange,
        sec_passages=sec_passages,
        issuer_sources=issuer_sources,
        clinical_search=clinical_search,
        regulatory_sources=regulatory_sources,
    )
    content_hash = hashlib.sha256(
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return LoadedPrimarySourcePlan(
        contract_version=contract_version,
        plan_id=plan_id,
        revision=revision,
        effective_at=effective_at,
        question_type=question_type,
        workflow_config_version=workflow_config_version,
        question_type_version=workflow.question_type_version,
        thesis_contract_id=workflow.thesis_contract_id,
        eligibility_policy_version=workflow.eligibility_policy_version,
        security_id=security_id,
        cik=cik,
        issuer_name=issuer_name,
        primary_listing_exchange=primary_listing_exchange,
        sec_passages=sec_passages,
        issuer_sources=issuer_sources,
        clinical_trial_search=clinical_search,
        regulatory_sources=regulatory_sources,
        content_hash=content_hash,
    )


def bind_primary_source_plan(
    loaded: LoadedPrimarySourcePlan,
    request: PrimarySourceRequest,
    *,
    trusted_issuer_hosts: tuple[str, ...],
    workflow_registry: WorkflowConfigRegistry = (
        DEFAULT_WORKFLOW_CONFIG_REGISTRY
    ),
) -> PrimarySourcePlan:
    workflow = workflow_registry.resolve(
        loaded.question_type,
        loaded.workflow_config_version,
    )
    if (
        loaded.contract_version not in _SUPPORTED_PLAN_VERSIONS
        or workflow is None
        or not workflow.active
        or loaded.question_type_version != workflow.question_type_version
        or loaded.thesis_contract_id != workflow.thesis_contract_id
        or loaded.eligibility_policy_version
        != workflow.eligibility_policy_version
        or loaded.effective_at.tzinfo is None
        or loaded.effective_at.utcoffset() is None
    ):
        raise PrimarySourcePlanError(
            "loaded source plan integrity is invalid"
        )
    try:
        validated_plan_id = _uuid(loaded.plan_id, "source plan ID")
        validated_sec_passages = tuple(
            sorted(
                (
                    _sec_passage(
                        _canonical_sec_passage(
                            passage,
                            contract_version=loaded.contract_version,
                        ),
                        contract_version=loaded.contract_version,
                    )
                    for passage in loaded.sec_passages
                ),
                key=lambda passage: passage.reference_key,
            )
        )
        _validate_sec_passage_cardinality(
            loaded.contract_version,
            validated_sec_passages,
        )
        validated_issuer_sources = _locators(
            tuple(_canonical_locator(source) for source in loaded.issuer_sources),
            lane="issuer",
        )
        validated_regulatory_sources = _locators(
            tuple(
                _canonical_locator(source)
                for source in loaded.regulatory_sources
            ),
            lane="regulatory",
        )
        validated_clinical_search = _clinical_search(
            {
                "program_name": loaded.clinical_trial_search.program_name,
                "search_terms": list(
                    loaded.clinical_trial_search.search_terms
                ),
                "allowed_sponsor_names": list(
                    loaded.clinical_trial_search.allowed_sponsor_names
                ),
            }
        )
    except (AttributeError, PrimarySourcePlanError, TypeError) as error:
        raise PrimarySourcePlanError(
            "loaded source plan integrity is invalid"
        ) from error
    if (
        validated_plan_id != loaded.plan_id
        or isinstance(loaded.revision, bool)
        or not isinstance(loaded.revision, int)
        or loaded.revision < 1
        or not loaded.sec_passages
        or validated_sec_passages != loaded.sec_passages
        or validated_issuer_sources != loaded.issuer_sources
        or validated_regulatory_sources != loaded.regulatory_sources
        or validated_clinical_search != loaded.clinical_trial_search
    ):
        raise PrimarySourcePlanError(
            "loaded source plan integrity is invalid"
        )
    canonical = _canonical_payload(
        contract_version=loaded.contract_version,
        plan_id=loaded.plan_id,
        revision=loaded.revision,
        effective_at=loaded.effective_at.astimezone(UTC),
        question_type=loaded.question_type,
        workflow_config_version=loaded.workflow_config_version,
        security_id=loaded.security_id,
        cik=loaded.cik,
        issuer_name=loaded.issuer_name,
        primary_listing_exchange=loaded.primary_listing_exchange,
        sec_passages=loaded.sec_passages,
        issuer_sources=loaded.issuer_sources,
        clinical_search=loaded.clinical_trial_search,
        regulatory_sources=loaded.regulatory_sources,
    )
    observed_hash = hashlib.sha256(
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if observed_hash != loaded.content_hash:
        raise PrimarySourcePlanError(
            "loaded source plan integrity is invalid"
        )
    identity = (
        loaded.security_id,
        loaded.cik,
        loaded.issuer_name,
        loaded.primary_listing_exchange,
    )
    expected = (
        request.security_id,
        request.cik,
        request.issuer_name,
        request.primary_listing_exchange,
    )
    if identity != expected:
        raise PrimarySourcePlanError(
            "source plan identity does not match request"
        )
    if loaded.effective_at > request.as_of_cutoff:
        raise PrimarySourcePlanError(
            "source plan is effective after request cutoff"
        )
    normalized_hosts = tuple(
        sorted({_text(host, "trusted issuer host").casefold() for host in trusted_issuer_hosts})
    )
    if not normalized_hosts:
        raise PrimarySourcePlanError("trusted issuer hosts must not be empty")
    source_hosts = {
        _https_host(source.source_url, "issuer source")
        for source in loaded.issuer_sources
    }
    if not source_hosts <= set(normalized_hosts):
        raise PrimarySourcePlanError("issuer source origin is not trusted")
    return PrimarySourcePlan(
        loaded=loaded,
        operator_id=request.operator_id,
        as_of_cutoff=request.as_of_cutoff,
        trusted_issuer_hosts=normalized_hosts,
    )


def _revalidate_bound_plan(plan: PrimarySourcePlan) -> PrimarySourcePlan:
    try:
        request = PrimarySourceRequest(
            operator_id=plan.operator_id,
            security_id=plan.loaded.security_id,
            cik=plan.loaded.cik,
            issuer_name=plan.loaded.issuer_name,
            primary_listing_exchange=(
                plan.loaded.primary_listing_exchange
            ),
            as_of_cutoff=plan.as_of_cutoff,
        )
        validated = bind_primary_source_plan(
            plan.loaded,
            request,
            trusted_issuer_hosts=plan.trusted_issuer_hosts,
        )
    except (AttributeError, PrimarySourcePlanError, ValueError) as error:
        raise PrimarySourcePlanError(
            "bound source plan integrity is invalid"
        ) from error
    if validated != plan:
        raise PrimarySourcePlanError(
            "bound source plan integrity is invalid"
        )
    return validated


def resolve_sec_passage_sources(
    plan: PrimarySourcePlan,
    documents: SecFilingDocumentSnapshot,
) -> tuple[ResolvedSecPassageSource, ...]:
    validated = _revalidate_bound_plan(plan)
    if (
        documents.operator_id != validated.operator_id
        or documents.security_id != validated.loaded.security_id
        or documents.cik != validated.loaded.cik
        or documents.as_of_cutoff != validated.as_of_cutoff
        or documents.policy_version != "biotech-required-sec-filings-v1"
    ):
        raise PrimarySourcePlanError(
            "SEC documents do not match bound source plan"
        )
    resolved: list[ResolvedSecPassageSource] = []
    for passage_plan in validated.sec_passages:
        matching = tuple(
            document
            for document in documents.documents
            if (
                document.form == passage_plan.selected_form
                and (
                    passage_plan.selected_accession_number is None
                    or document.accession_number
                    == passage_plan.selected_accession_number
                )
            )
        )
        if len(matching) != 1:
            raise PrimarySourcePlanError(
                "SEC selected form is missing or ambiguous"
            )
        resolved.append(
            ResolvedSecPassageSource(
                plan=passage_plan,
                document=matching[0],
            )
        )
    return tuple(
        sorted(
            resolved,
            key=lambda item: item.plan.reference_key,
        )
    )


class InMemoryPrimarySourcePlanRepository:
    def __init__(self) -> None:
        self._plans: dict[
            tuple[str, int],
            LoadedPrimarySourcePlan,
        ] = {}
        self._bindings: dict[
            tuple[str, str],
            PrimarySourcePlanRunBinding,
        ] = {}

    def save(
        self,
        plan: PrimarySourcePlan,
    ) -> LoadedPrimarySourcePlan:
        validated = _revalidate_bound_plan(plan)
        key = (
            validated.loaded.plan_id,
            validated.loaded.revision,
        )
        existing = self._plans.get(key)
        if existing is not None:
            if existing != validated.loaded:
                raise PrimarySourcePlanError(
                    "conflicting immutable source plan revision"
                )
            return existing
        self._plans[key] = validated.loaded
        return validated.loaded

    def bind_to_run(
        self,
        plan: PrimarySourcePlan,
        research_run: ResearchRun,
    ) -> PrimarySourcePlanRunBinding:
        try:
            canonical_run_id = str(UUID(research_run.id))
        except (AttributeError, TypeError, ValueError) as error:
            raise PrimarySourcePlanError(
                "research run ID must be a UUID"
            ) from error
        saved = self.save(plan)
        run_identity = (
            research_run.operator_id,
            research_run.security_id,
            research_run.as_of_cutoff,
            research_run.question_type,
            research_run.question_type_version,
            research_run.workflow_config_version,
            research_run.thesis_contract_id,
            research_run.eligibility.policy_version,
        )
        expected_identity = (
            plan.operator_id,
            saved.security_id,
            plan.as_of_cutoff,
            saved.question_type,
            saved.question_type_version,
            saved.workflow_config_version,
            saved.thesis_contract_id,
            saved.eligibility_policy_version,
        )
        if run_identity != expected_identity:
            raise PrimarySourcePlanError(
                "Research Run does not match source plan"
            )
        binding = PrimarySourcePlanRunBinding(
            operator_id=plan.operator_id,
            research_run_id=canonical_run_id,
            security_id=saved.security_id,
            as_of_cutoff=plan.as_of_cutoff,
            question_type=saved.question_type,
            workflow_config_version=saved.workflow_config_version,
            plan_id=saved.plan_id,
            plan_revision=saved.revision,
            plan_content_hash=saved.content_hash,
        )
        key = (binding.operator_id, binding.research_run_id)
        existing = self._bindings.get(key)
        if existing is not None:
            if existing != binding:
                raise PrimarySourcePlanError(
                    "research run already has another source plan"
                )
            return existing
        self._bindings[key] = binding
        return binding

    def get_plan(
        self,
        plan_id: str,
        revision: int,
    ) -> LoadedPrimarySourcePlan | None:
        return self._plans.get((plan_id, revision))

    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> PrimarySourcePlanRunBinding | None:
        return self._bindings.get((operator_id, research_run_id))


__all__ = [
    "InMemoryPrimarySourcePlanRepository",
    "PRIMARY_SOURCE_PLAN_VERSION",
    "PRIMARY_SOURCE_PLAN_V1",
    "PRIMARY_SOURCE_PLAN_V2",
    "PRIMARY_SOURCE_PLAN_V3",
    "LoadedPrimarySourcePlan",
    "PrimarySourcePlan",
    "PrimarySourcePlanError",
    "PrimarySourcePlanRunBinding",
    "ResolvedSecPassageSource",
    "SecPassagePlan",
    "bind_primary_source_plan",
    "load_primary_source_plan",
    "resolve_sec_passage_sources",
]
