from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
from pathlib import PurePosixPath
import re
import stat
from threading import Lock
from urllib.parse import urlencode, urlsplit
from uuid import UUID
from zipfile import BadZipFile, LargeZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from workers.clinical_trials.collector import ClinicalTrialsTransportResponse
from workers.official_sources.models import OfficialBytesResponse
from workers.sec.collector import BytesResponse

from .models import PrimarySourceRequest
from .plans import (
    PrimarySourcePlan,
    PrimarySourcePlanError,
    bind_primary_source_plan,
    load_primary_source_plan,
)


CAPTURE_CONTRACT_VERSION = "primary_source_capture.v1"
CAPTURE_LOADER_VERSION = "primary-source-capture-loader-v1"
_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MAX_MEMBER_BYTES = 32 * 1024 * 1024
_MAX_TOTAL_MEMBER_BYTES = 128 * 1024 * 1024
_MAX_MEMBERS = 256
_MAX_COMPRESSION_RATIO = 200
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RESPONSE_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,79}$")
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_NCT_ID = re.compile(r"^NCT[0-9]{8}$")
_ARCHIVE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_HISTORY_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}\.json$")
_ALLOWED_HEADERS = frozenset(
    {"content-type", "etag", "last-modified", "content-length"}
)
_JSON_ROLES = frozenset(
    {
        "sec_security_registry",
        "sec_submissions_root",
        "sec_submissions_history",
        "sec_companyfacts",
        "clinical_trials_page",
        "clinical_trials_history_summary",
        "clinical_trials_history_version",
    }
)
_SEC_HTML_ROLES = frozenset(
    {
        "sec_filing_document",
        "sec_filing_index",
        "sec_filing_exhibit",
    }
)
_OFFICIAL_ROLES = frozenset(
    {"issuer_document", "regulatory_document"}
)
_SEC_TRANSPORT_ROLES = frozenset(
    {
        "sec_security_registry",
        "sec_submissions_root",
        "sec_submissions_history",
        "sec_companyfacts",
        *_SEC_HTML_ROLES,
    }
)
_CORE_ROLES = frozenset(
    {
        "sec_security_registry",
        "sec_submissions_root",
        "sec_companyfacts",
        "sec_filing_document",
        "sec_filing_index",
        "issuer_document",
        "clinical_trials_page",
        "regulatory_document",
    }
)
_ROUTE_FIELDS = {
    "sec_security_registry": frozenset({"role"}),
    "sec_submissions_root": frozenset({"role"}),
    "sec_submissions_history": frozenset({"role", "history_file"}),
    "sec_companyfacts": frozenset({"role"}),
    "sec_filing_document": frozenset(
        {"role", "accession_number", "primary_document"}
    ),
    "sec_filing_index": frozenset({"role", "accession_number"}),
    "sec_filing_exhibit": frozenset(
        {
            "role",
            "accession_number",
            "exhibit_type",
            "document_name",
        }
    ),
    "issuer_document": frozenset({"role", "source_key"}),
    "clinical_trials_page": frozenset({"role", "page_ordinal"}),
    "clinical_trials_history_summary": frozenset({"role", "nct_id"}),
    "clinical_trials_history_version": frozenset(
        {"role", "nct_id", "version"}
    ),
    "regulatory_document": frozenset({"role", "source_key"}),
}
_TOP_LEVEL_FIELDS = frozenset(
    {
        "contract_version",
        "capture_id",
        "revision",
        "provenance_mode",
        "assembled_at",
        "context",
        "plan",
        "responses",
    }
)
_CONTEXT_FIELDS = frozenset(
    {
        "operator_id",
        "security_id",
        "cik",
        "issuer_name",
        "primary_listing_exchange",
        "as_of_cutoff",
        "question_type",
        "workflow_config_version",
    }
)
_PLAN_FIELDS = frozenset({"path", "plan_id", "revision", "content_hash"})
_RESPONSE_FIELDS = frozenset(
    {
        "response_key",
        "route",
        "request_url",
        "final_url",
        "status",
        "headers",
        "retrieved_at",
        "body",
    }
)
_BODY_FIELDS = frozenset({"path", "byte_length", "sha256"})


class PrimarySourceCaptureError(ValueError):
    """Raised when an offline primary-source capture is not trustworthy."""


class CaptureMiss(PrimarySourceCaptureError):
    """Raised when replay requests an uncaptured or disallowed exact URL."""


@dataclass(frozen=True, slots=True)
class CapturedResponse:
    response_key: str
    role: str
    route: tuple[tuple[str, object], ...]
    request_url: str
    final_url: str
    status: int
    headers: tuple[tuple[str, str], ...]
    retrieved_at: datetime
    body_path: str
    byte_length: int
    body_sha256: str


@dataclass(frozen=True, slots=True)
class CaptureAcceptanceReceipt:
    capture_id: str
    capture_revision: int
    package_sha256: str
    capture_content_hash: str
    authenticated_operator_id: str
    accepted_at: datetime
    loader_version: str
    provenance_mode: str


@dataclass(frozen=True, slots=True)
class PrimarySourceCapture:
    contract_version: str
    capture_id: str
    revision: int
    provenance_mode: str
    assembled_at: datetime
    plan: PrimarySourcePlan
    responses: tuple[CapturedResponse, ...]
    bodies: tuple[tuple[str, bytes], ...]
    content_hash: str
    receipt: CaptureAcceptanceReceipt

    def open_session(self) -> PrimarySourceCaptureSession:
        return PrimarySourceCaptureSession(self)

    def body(self, body_sha256: str) -> bytes:
        try:
            return dict(self.bodies)[body_sha256]
        except KeyError as error:
            raise PrimarySourceCaptureError(
                "capture response body is unavailable"
            ) from error


class _CaptureTransport:
    def __init__(
        self,
        session: PrimarySourceCaptureSession,
        allowed_roles: frozenset[str],
        response_factory: Callable[
            [CapturedResponse, bytes],
            object,
        ],
    ) -> None:
        self._session = session
        self._allowed_roles = allowed_roles
        self._response_factory = response_factory
        self._last_retrieved_at: datetime | None = None

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ):
        del headers
        record, body = self._session._consume(
            url,
            self._allowed_roles,
        )
        self._last_retrieved_at = record.retrieved_at
        return self._response_factory(record, body)

    def clock(self) -> datetime:
        if self._last_retrieved_at is None:
            raise PrimarySourceCaptureError(
                "capture clock requested before replay"
            )
        return self._last_retrieved_at


class PrimarySourceCaptureSession:
    def __init__(self, capture: PrimarySourceCapture) -> None:
        self.capture = capture
        self._responses = {
            response.request_url: response
            for response in capture.responses
        }
        self._consumed: set[str] = set()
        self._lock = Lock()

    def _consume(
        self,
        url: str,
        allowed_roles: frozenset[str],
    ) -> tuple[CapturedResponse, bytes]:
        with self._lock:
            response = self._responses.get(url)
            if response is None or response.role not in allowed_roles:
                raise CaptureMiss(
                    "exact capture response is unavailable"
                )
            self._consumed.add(url)
        return response, self.capture.body(response.body_sha256)

    def sec_transport(self) -> _CaptureTransport:
        return _CaptureTransport(
            self,
            _SEC_TRANSPORT_ROLES,
            lambda record, body: BytesResponse(
                body=body,
                status=record.status,
                headers=dict(record.headers),
                final_url=record.final_url,
            ),
        )

    def official_transport(self, role: str) -> _CaptureTransport:
        if role not in _OFFICIAL_ROLES:
            raise PrimarySourceCaptureError(
                "official capture role is invalid"
            )
        return _CaptureTransport(
            self,
            frozenset({role}),
            lambda record, body: OfficialBytesResponse(
                body=body,
                status=record.status,
                headers=dict(record.headers),
                final_url=record.final_url,
            ),
        )

    def clinical_trials_transport(self) -> _CaptureTransport:
        return _CaptureTransport(
            self,
            frozenset(
                {
                    "clinical_trials_page",
                    "clinical_trials_history_summary",
                    "clinical_trials_history_version",
                }
            ),
            lambda record, body: ClinicalTrialsTransportResponse(
                body=body,
                status=record.status,
                headers=dict(record.headers),
                final_url=record.final_url,
            ),
        )

    def assert_all_consumed(self) -> None:
        missing = tuple(
            response.response_key
            for response in self.capture.responses
            if response.request_url not in self._consumed
        )
        if missing:
            raise PrimarySourceCaptureError(
                "unconsumed capture responses: " + ", ".join(missing)
            )


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PrimarySourceCaptureError(
                "capture JSON contains duplicate fields"
            )
        result[key] = value
    return result


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise PrimarySourceCaptureError(f"{label} must be an object")
    return value


def _fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    label: str,
) -> None:
    if frozenset(value) != expected:
        raise PrimarySourceCaptureError(f"{label} fields are invalid")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PrimarySourceCaptureError(f"{label} is required")
    return value.strip()


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PrimarySourceCaptureError(f"{label} is invalid")
    return value


def _timestamp(value: object, label: str) -> datetime:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise PrimarySourceCaptureError(f"{label} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PrimarySourceCaptureError(f"{label} must include timezone")
    return parsed.astimezone(UTC)


def _uuid(value: object, label: str) -> str:
    text = _text(value, label)
    try:
        return str(UUID(text))
    except ValueError as error:
        raise PrimarySourceCaptureError(f"{label} must be a UUID") from error


def _sha256(value: object, label: str) -> str:
    text = _text(value, label)
    if _SHA256.fullmatch(text) is None:
        raise PrimarySourceCaptureError(f"{label} is invalid")
    return text


def _https_url(value: object, label: str):
    text = _text(value, label)
    parsed = urlsplit(text)
    try:
        port = parsed.port
    except ValueError as error:
        raise PrimarySourceCaptureError(f"{label} origin is invalid") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        raise PrimarySourceCaptureError(f"{label} origin is invalid")
    return text, parsed


def _route(value: object) -> tuple[str, tuple[tuple[str, object], ...]]:
    route = _mapping(value, "capture route")
    role = _text(route.get("role"), "capture role")
    expected = _ROUTE_FIELDS.get(role)
    if expected is None or frozenset(route) != expected:
        raise PrimarySourceCaptureError("capture route fields are invalid")
    if role == "sec_submissions_history":
        history_file = _text(route["history_file"], "SEC history file")
        if _HISTORY_FILE.fullmatch(history_file) is None:
            raise PrimarySourceCaptureError("SEC history file is invalid")
    if role in {
        "sec_filing_document",
        "sec_filing_index",
        "sec_filing_exhibit",
    }:
        accession = _text(route["accession_number"], "SEC accession")
        if _ACCESSION.fullmatch(accession) is None:
            raise PrimarySourceCaptureError("SEC accession is invalid")
    if role == "sec_filing_document":
        if (
            _ARCHIVE_FILE.fullmatch(
                _text(route["primary_document"], "SEC primary document")
            )
            is None
        ):
            raise PrimarySourceCaptureError(
                "SEC primary document is invalid"
            )
    if role == "sec_filing_exhibit":
        exhibit_type = _text(route["exhibit_type"], "SEC exhibit type")
        if not exhibit_type.upper().startswith("EX-"):
            raise PrimarySourceCaptureError("SEC exhibit type is invalid")
        if (
            _ARCHIVE_FILE.fullmatch(
                _text(route["document_name"], "SEC exhibit document")
            )
            is None
        ):
            raise PrimarySourceCaptureError(
                "SEC exhibit document is invalid"
            )
    if role in {"issuer_document", "regulatory_document"}:
        _text(route["source_key"], "official source key")
    if role == "clinical_trials_page":
        _integer(route["page_ordinal"], "clinical page ordinal")
    if role in {
        "clinical_trials_history_summary",
        "clinical_trials_history_version",
    }:
        nct_id = _text(route["nct_id"], "clinical NCT ID")
        if _NCT_ID.fullmatch(nct_id) is None:
            raise PrimarySourceCaptureError("clinical NCT ID is invalid")
    if role == "clinical_trials_history_version":
        _integer(route["version"], "clinical history version")
    return role, tuple(sorted(route.items()))


def _clinical_base_url(plan: PrimarySourcePlan) -> str:
    query = " OR ".join(
        f'"{term}"' for term in plan.clinical_trial_search.search_terms
    )
    return "https://clinicaltrials.gov/api/v2/studies?" + urlencode(
        {
            "format": "json",
            "pageSize": 100,
            "countTotal": "true",
            "query.term": query,
        }
    )


def _sec_archive_prefix(cik: str, accession: str) -> str:
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik.lstrip('0') or '0'}/"
        f"{accession.replace('-', '')}/"
    )


def _validate_route_url(
    *,
    role: str,
    route: Mapping[str, object],
    request_url: str,
    final_url: str,
    plan: PrimarySourcePlan,
) -> None:
    request_text, request_parts = _https_url(
        request_url,
        "capture request URL",
    )
    final_text, final_parts = _https_url(
        final_url,
        "capture final URL",
    )
    cik = plan.loaded.cik
    if role == "sec_security_registry":
        expected = "https://www.sec.gov/files/company_tickers_exchange.json"
    elif role == "sec_submissions_root":
        expected = f"https://data.sec.gov/submissions/CIK{cik}.json"
    elif role == "sec_submissions_history":
        expected = (
            "https://data.sec.gov/submissions/"
            f"{route['history_file']}"
        )
    elif role == "sec_companyfacts":
        expected = (
            "https://data.sec.gov/api/xbrl/companyfacts/"
            f"CIK{cik}.json"
        )
    elif role == "sec_filing_document":
        accession = str(route["accession_number"])
        expected = (
            _sec_archive_prefix(cik, accession)
            + str(route["primary_document"])
        )
    elif role == "sec_filing_index":
        accession = str(route["accession_number"])
        expected = (
            _sec_archive_prefix(cik, accession)
            + f"{accession}-index.html"
        )
    elif role == "sec_filing_exhibit":
        accession = str(route["accession_number"])
        expected = (
            _sec_archive_prefix(cik, accession)
            + str(route["document_name"])
        )
    elif role == "clinical_trials_page":
        base_url = _clinical_base_url(plan)
        ordinal = int(route["page_ordinal"])
        if ordinal == 0:
            expected = base_url
        elif (
            request_text.startswith(base_url + "&pageToken=")
            and request_text[len(base_url + "&pageToken=") :]
        ):
            expected = request_text
        else:
            raise PrimarySourceCaptureError(
                "capture route origin is invalid"
            )
    elif role == "clinical_trials_history_summary":
        expected = (
            "https://clinicaltrials.gov/api/int/studies/"
            f"{route['nct_id']}?history=true"
        )
    elif role == "clinical_trials_history_version":
        expected = (
            "https://clinicaltrials.gov/api/int/studies/"
            f"{route['nct_id']}/history/{route['version']}"
        )
    elif role in {"issuer_document", "regulatory_document"}:
        sources = (
            plan.issuer_sources
            if role == "issuer_document"
            else plan.regulatory_sources
        )
        source_key = str(route["source_key"])
        matching = tuple(
            source
            for source in sources
            if source.source_key == source_key
        )
        if len(matching) != 1:
            raise PrimarySourceCaptureError(
                "capture route does not match source plan"
            )
        expected = matching[0].source_url
    else:
        raise PrimarySourceCaptureError("capture route is unsupported")
    if request_text != expected:
        raise PrimarySourceCaptureError(
            "capture route origin is invalid"
        )
    if role in _SEC_TRANSPORT_ROLES | {
        "clinical_trials_page",
        "clinical_trials_history_summary",
        "clinical_trials_history_version",
    }:
        if final_text != request_text:
            raise PrimarySourceCaptureError(
                "capture final URL is invalid"
            )
    elif role == "issuer_document":
        if (final_parts.hostname or "").casefold() not in set(
            plan.trusted_issuer_hosts
        ):
            raise PrimarySourceCaptureError(
                "capture final URL is invalid"
            )
    elif role == "regulatory_document":
        if (final_parts.hostname or "").casefold() not in {
            "accessdata.fda.gov",
            "fda.gov",
            "precision.fda.gov",
            "www.accessdata.fda.gov",
            "www.fda.gov",
        }:
            raise PrimarySourceCaptureError(
                "capture final URL is invalid"
            )
    del request_parts


def _headers(
    value: object,
    *,
    role: str,
    body_length: int,
) -> tuple[tuple[str, str], ...]:
    headers = _mapping(value, "capture response headers")
    if not headers or any(
        not isinstance(key, str)
        or key != key.casefold()
        or key not in _ALLOWED_HEADERS
        or not isinstance(item, str)
        or not item.strip()
        for key, item in headers.items()
    ):
        raise PrimarySourceCaptureError(
            "capture response headers are invalid"
        )
    content_type = headers.get("content-type")
    if not isinstance(content_type, str):
        raise PrimarySourceCaptureError(
            "capture response media type is invalid"
        )
    media_type = content_type.partition(";")[0].strip().casefold()
    allowed_media = (
        {"application/json"}
        if role in _JSON_ROLES
        else (
            {"text/html", "application/xhtml+xml"}
            if role in _SEC_HTML_ROLES
            else (
                {
                    "application/json",
                    "text/html",
                    "application/xhtml+xml",
                    "text/plain",
                }
                if role == "regulatory_document"
                else {
                    "text/html",
                    "application/xhtml+xml",
                    "text/plain",
                }
            )
        )
    )
    if media_type not in allowed_media:
        raise PrimarySourceCaptureError(
            "capture response media type is invalid"
        )
    content_length = headers.get("content-length")
    if content_length is not None and content_length != str(body_length):
        raise PrimarySourceCaptureError(
            "capture response content length is invalid"
        )
    return tuple(sorted((key, item.strip()) for key, item in headers.items()))


def _archive_entries(raw_archive: bytes) -> tuple[dict[str, bytes], str]:
    if not isinstance(raw_archive, bytes) or not raw_archive:
        raise PrimarySourceCaptureError(
            "capture archive must be non-empty bytes"
        )
    if len(raw_archive) > _MAX_ARCHIVE_BYTES:
        raise PrimarySourceCaptureError("capture archive is too large")
    try:
        with ZipFile(BytesIO(raw_archive), "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(infos) > _MAX_MEMBERS:
                raise PrimarySourceCaptureError(
                    "capture archive has too many members"
                )
            if len(names) != len(set(names)):
                raise PrimarySourceCaptureError(
                    "duplicate archive member"
                )
            total_size = 0
            entries: dict[str, bytes] = {}
            for info in infos:
                path = PurePosixPath(info.filename)
                if (
                    info.is_dir()
                    or info.filename.startswith("/")
                    or "\\" in info.filename
                    or ".." in path.parts
                    or str(path) != info.filename
                ):
                    raise PrimarySourceCaptureError(
                        "capture archive member path is invalid"
                    )
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise PrimarySourceCaptureError(
                        "capture archive symlink is invalid"
                    )
                if info.flag_bits & 0x1:
                    raise PrimarySourceCaptureError(
                        "encrypted capture archive is invalid"
                    )
                if info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
                    raise PrimarySourceCaptureError(
                        "capture archive compression is invalid"
                    )
                if info.file_size > _MAX_MEMBER_BYTES:
                    raise PrimarySourceCaptureError(
                        "capture archive member is too large"
                    )
                total_size += info.file_size
                if total_size > _MAX_TOTAL_MEMBER_BYTES:
                    raise PrimarySourceCaptureError(
                        "capture archive expanded size is too large"
                    )
                if (
                    info.file_size
                    and (
                        info.compress_size == 0
                        or info.file_size
                        > info.compress_size * _MAX_COMPRESSION_RATIO
                    )
                ):
                    raise PrimarySourceCaptureError(
                        "capture archive compression ratio is invalid"
                    )
                entries[info.filename] = archive.read(info)
    except (BadZipFile, LargeZipFile) as error:
        raise PrimarySourceCaptureError(
            "capture archive is invalid"
        ) from error
    return entries, hashlib.sha256(raw_archive).hexdigest()


def _parse_json(raw: bytes, label: str) -> Mapping[str, object]:
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise PrimarySourceCaptureError(f"{label} is invalid") from error
    return _mapping(value, label)


def _canonical_response(response: CapturedResponse) -> dict[str, object]:
    return {
        "response_key": response.response_key,
        "route": dict(response.route),
        "request_url": response.request_url,
        "final_url": response.final_url,
        "status": response.status,
        "headers": dict(response.headers),
        "retrieved_at": response.retrieved_at.isoformat(),
        "body": {
            "path": response.body_path,
            "byte_length": response.byte_length,
            "sha256": response.body_sha256,
        },
    }


def _validate_clinical_pagination(
    responses: list[CapturedResponse],
    bodies: Mapping[str, bytes],
    plan: PrimarySourcePlan,
) -> None:
    pages = sorted(
        (
            response
            for response in responses
            if response.role == "clinical_trials_page"
        ),
        key=lambda response: int(dict(response.route)["page_ordinal"]),
    )
    ordinals = tuple(
        int(dict(response.route)["page_ordinal"])
        for response in pages
    )
    if ordinals != tuple(range(len(pages))):
        raise PrimarySourceCaptureError(
            "clinical capture pagination is invalid"
        )
    expected_url = _clinical_base_url(plan)
    for ordinal, response in enumerate(pages):
        if response.request_url != expected_url:
            raise PrimarySourceCaptureError(
                "clinical capture pagination is invalid"
            )
        try:
            payload = json.loads(
                bodies[response.body_sha256].decode("utf-8")
            )
        except (
            KeyError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            raise PrimarySourceCaptureError(
                "clinical capture pagination is invalid"
            ) from error
        if not isinstance(payload, Mapping):
            raise PrimarySourceCaptureError(
                "clinical capture pagination is invalid"
            )
        next_token = payload.get("nextPageToken")
        if next_token is None:
            if ordinal != len(pages) - 1:
                raise PrimarySourceCaptureError(
                    "clinical capture pagination is invalid"
                )
            continue
        if not isinstance(next_token, str) or not next_token.strip():
            raise PrimarySourceCaptureError(
                "clinical capture pagination is invalid"
            )
        if ordinal == len(pages) - 1:
            raise PrimarySourceCaptureError(
                "clinical capture pagination is invalid"
            )
        expected_url = (
            _clinical_base_url(plan)
            + "&"
            + urlencode({"pageToken": next_token})
        )


def _clinical_nct_id(study: object) -> str:
    try:
        protocol = _mapping(study, "clinical study").get("protocolSection")
        identity = _mapping(
            _mapping(protocol, "clinical protocol").get(
                "identificationModule"
            ),
            "clinical identity",
        )
        nct_id = _text(identity.get("nctId"), "clinical NCT ID")
    except PrimarySourceCaptureError as error:
        raise PrimarySourceCaptureError(
            "clinical history is invalid"
        ) from error
    if _NCT_ID.fullmatch(nct_id) is None:
        raise PrimarySourceCaptureError("clinical history is invalid")
    return nct_id


def _clinical_json(
    response: CapturedResponse,
    bodies: Mapping[str, bytes],
) -> Mapping[str, object]:
    try:
        payload = json.loads(
            bodies[response.body_sha256].decode("utf-8")
        )
    except (
        KeyError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise PrimarySourceCaptureError(
            "clinical history is invalid"
        ) from error
    if not isinstance(payload, Mapping):
        raise PrimarySourceCaptureError("clinical history is invalid")
    return payload


def _validate_clinical_history(
    responses: list[CapturedResponse],
    bodies: Mapping[str, bytes],
) -> None:
    search_nct_ids: set[str] = set()
    summaries: dict[str, set[int]] = {}
    for response in responses:
        if response.role != "clinical_trials_page":
            continue
        payload = _clinical_json(response, bodies)
        studies = payload.get("studies")
        if not isinstance(studies, list):
            raise PrimarySourceCaptureError(
                "clinical history is invalid"
            )
        search_nct_ids.update(_clinical_nct_id(study) for study in studies)
    for response in responses:
        if response.role != "clinical_trials_history_summary":
            continue
        route = dict(response.route)
        nct_id = str(route["nct_id"])
        payload = _clinical_json(response, bodies)
        if _clinical_nct_id(payload.get("study")) != nct_id:
            raise PrimarySourceCaptureError(
                "clinical history is invalid"
            )
        history = _mapping(payload.get("history"), "clinical history")
        changes = history.get("changes")
        if not isinstance(changes, list):
            raise PrimarySourceCaptureError(
                "clinical history is invalid"
            )
        versions: set[int] = set()
        for change in changes:
            if not isinstance(change, Mapping):
                raise PrimarySourceCaptureError(
                    "clinical history is invalid"
                )
            version = change.get("version")
            if (
                isinstance(version, bool)
                or not isinstance(version, int)
                or version < 0
                or version in versions
            ):
                raise PrimarySourceCaptureError(
                    "clinical history is invalid"
                )
            versions.add(version)
        if nct_id not in search_nct_ids or nct_id in summaries:
            raise PrimarySourceCaptureError(
                "clinical history is invalid"
            )
        summaries[nct_id] = versions
    for response in responses:
        if response.role != "clinical_trials_history_version":
            continue
        route = dict(response.route)
        nct_id = str(route["nct_id"])
        version = int(route["version"])
        payload = _clinical_json(response, bodies)
        if (
            nct_id not in summaries
            or version not in summaries[nct_id]
            or payload.get("studyVersion") != version
            or _clinical_nct_id(payload.get("study")) != nct_id
        ):
            raise PrimarySourceCaptureError(
                "clinical history is invalid"
            )


def load_primary_source_capture(
    raw_archive: bytes,
    *,
    request: PrimarySourceRequest,
    trusted_issuer_hosts: tuple[str, ...],
    accepted_at: Callable[[], datetime],
) -> PrimarySourceCapture:
    entries, package_sha256 = _archive_entries(raw_archive)
    if "capture.json" not in entries or "primary-source-plan.json" not in entries:
        raise PrimarySourceCaptureError(
            "capture archive members are invalid"
        )
    manifest = _parse_json(entries["capture.json"], "capture manifest")
    _fields(manifest, _TOP_LEVEL_FIELDS, "capture manifest")
    contract_version = _text(
        manifest["contract_version"],
        "capture contract version",
    )
    if contract_version != CAPTURE_CONTRACT_VERSION:
        raise PrimarySourceCaptureError(
            "capture contract version is unsupported"
        )
    capture_id = _uuid(manifest["capture_id"], "capture ID")
    revision = _integer(
        manifest["revision"],
        "capture revision",
        minimum=1,
    )
    provenance_mode = _text(
        manifest["provenance_mode"],
        "capture provenance mode",
    )
    if provenance_mode != "operator_supplied_unverified":
        raise PrimarySourceCaptureError(
            "capture provenance mode is unsupported"
        )
    assembled_at = _timestamp(
        manifest["assembled_at"],
        "capture assembled time",
    )

    try:
        loaded_plan = load_primary_source_plan(
            entries["primary-source-plan.json"]
        )
        plan = bind_primary_source_plan(
            loaded_plan,
            request,
            trusted_issuer_hosts=trusted_issuer_hosts,
        )
    except PrimarySourcePlanError as error:
        raise PrimarySourceCaptureError(
            "embedded source plan is invalid"
        ) from error
    context = _mapping(manifest["context"], "capture context")
    _fields(context, _CONTEXT_FIELDS, "capture context")
    expected_context = {
        "operator_id": request.operator_id,
        "security_id": request.security_id,
        "cik": request.cik,
        "issuer_name": request.issuer_name,
        "primary_listing_exchange": request.primary_listing_exchange,
        "as_of_cutoff": request.as_of_cutoff.isoformat(),
        "question_type": plan.loaded.question_type,
        "workflow_config_version": plan.loaded.workflow_config_version,
    }
    if dict(context) != expected_context:
        raise PrimarySourceCaptureError(
            "capture context does not match request"
        )
    plan_reference = _mapping(manifest["plan"], "capture plan")
    _fields(plan_reference, _PLAN_FIELDS, "capture plan")
    expected_plan_reference = {
        "path": "primary-source-plan.json",
        "plan_id": plan.loaded.plan_id,
        "revision": plan.loaded.revision,
        "content_hash": plan.content_hash,
    }
    if dict(plan_reference) != expected_plan_reference:
        raise PrimarySourceCaptureError(
            "capture plan does not match embedded source plan"
        )
    raw_responses = manifest["responses"]
    if (
        not isinstance(raw_responses, list)
        or not raw_responses
        or len(raw_responses) > _MAX_MEMBERS - 2
    ):
        raise PrimarySourceCaptureError(
            "capture responses are invalid"
        )
    responses: list[CapturedResponse] = []
    required_paths = {"capture.json", "primary-source-plan.json"}
    response_keys: set[str] = set()
    request_urls: set[str] = set()
    bodies: dict[str, bytes] = {}
    for raw_response in raw_responses:
        response = _mapping(raw_response, "capture response")
        _fields(response, _RESPONSE_FIELDS, "capture response")
        response_key = _text(
            response["response_key"],
            "capture response key",
        )
        if (
            _RESPONSE_KEY.fullmatch(response_key) is None
            or response_key in response_keys
        ):
            raise PrimarySourceCaptureError(
                "capture response key is invalid"
            )
        response_keys.add(response_key)
        role, route_values = _route(response["route"])
        route_mapping = dict(route_values)
        request_url = _text(
            response["request_url"],
            "capture request URL",
        )
        final_url = _text(response["final_url"], "capture final URL")
        if request_url in request_urls:
            raise PrimarySourceCaptureError(
                "capture request URL must be unique"
            )
        request_urls.add(request_url)
        _validate_route_url(
            role=role,
            route=route_mapping,
            request_url=request_url,
            final_url=final_url,
            plan=plan,
        )
        status = _integer(
            response["status"],
            "capture response status",
            minimum=100,
        )
        if status > 599:
            raise PrimarySourceCaptureError(
                "capture response status is invalid"
            )
        retrieved_at = _timestamp(
            response["retrieved_at"],
            "capture response retrieval time",
        )
        if retrieved_at > assembled_at:
            raise PrimarySourceCaptureError(
                "capture response retrieval is after assembly"
            )
        body = _mapping(response["body"], "capture response body")
        _fields(body, _BODY_FIELDS, "capture response body")
        body_sha256 = _sha256(
            body["sha256"],
            "capture body SHA-256",
        )
        body_path = _text(body["path"], "capture body path")
        if body_path != f"payloads/{body_sha256}.bin":
            raise PrimarySourceCaptureError(
                "capture body path is invalid"
            )
        byte_length = _integer(
            body["byte_length"],
            "capture body length",
        )
        required_paths.add(body_path)
        captured_body = entries.get(body_path)
        if (
            captured_body is None
            or len(captured_body) != byte_length
            or hashlib.sha256(captured_body).hexdigest() != body_sha256
        ):
            raise PrimarySourceCaptureError(
                "capture body integrity is invalid"
            )
        if not captured_body:
            raise PrimarySourceCaptureError(
                "capture response body is empty"
            )
        headers = _headers(
            response["headers"],
            role=role,
            body_length=byte_length,
        )
        bodies[body_sha256] = captured_body
        responses.append(
            CapturedResponse(
                response_key=response_key,
                role=role,
                route=route_values,
                request_url=request_url,
                final_url=final_url,
                status=status,
                headers=headers,
                retrieved_at=retrieved_at,
                body_path=body_path,
                byte_length=byte_length,
                body_sha256=body_sha256,
            )
        )
    if set(entries) != required_paths:
        raise PrimarySourceCaptureError(
            "capture archive members are invalid"
        )
    roles = {response.role for response in responses}
    if not _CORE_ROLES <= roles:
        raise PrimarySourceCaptureError(
            "capture core responses are missing"
        )
    _validate_clinical_pagination(responses, bodies, plan)
    _validate_clinical_history(responses, bodies)
    ordered_responses = tuple(
        sorted(
            responses,
            key=lambda response: (
                response.role,
                response.response_key,
                response.request_url,
            ),
        )
    )
    canonical = {
        "contract_version": contract_version,
        "capture_id": capture_id,
        "revision": revision,
        "provenance_mode": provenance_mode,
        "assembled_at": assembled_at.isoformat(),
        "context": expected_context,
        "plan": expected_plan_reference,
        "responses": [
            _canonical_response(response)
            for response in ordered_responses
        ],
    }
    content_hash = hashlib.sha256(
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    accepted = accepted_at()
    if accepted.tzinfo is None or accepted.utcoffset() is None:
        raise PrimarySourceCaptureError(
            "capture acceptance clock must include timezone"
        )
    accepted = accepted.astimezone(UTC)
    if accepted < assembled_at:
        raise PrimarySourceCaptureError(
            "capture acceptance predates assembly"
        )
    receipt = CaptureAcceptanceReceipt(
        capture_id=capture_id,
        capture_revision=revision,
        package_sha256=package_sha256,
        capture_content_hash=content_hash,
        authenticated_operator_id=request.operator_id,
        accepted_at=accepted,
        loader_version=CAPTURE_LOADER_VERSION,
        provenance_mode=provenance_mode,
    )
    return PrimarySourceCapture(
        contract_version=contract_version,
        capture_id=capture_id,
        revision=revision,
        provenance_mode=provenance_mode,
        assembled_at=assembled_at,
        plan=plan,
        responses=ordered_responses,
        bodies=tuple(sorted(bodies.items())),
        content_hash=content_hash,
        receipt=receipt,
    )


__all__ = [
    "CAPTURE_CONTRACT_VERSION",
    "CAPTURE_LOADER_VERSION",
    "CaptureAcceptanceReceipt",
    "CaptureMiss",
    "CapturedResponse",
    "PrimarySourceCapture",
    "PrimarySourceCaptureError",
    "PrimarySourceCaptureSession",
    "load_primary_source_capture",
]
