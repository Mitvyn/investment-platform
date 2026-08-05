from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
import re
from threading import Lock
from typing import Protocol, TypeVar
from urllib.parse import urlencode
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from .captures import CAPTURE_CONTRACT_VERSION
from .models import PrimarySourceRequest
from .plans import (
    PrimarySourcePlan,
    bind_primary_source_plan,
    load_primary_source_plan,
)


_CAPTURE_HEADERS = frozenset(
    {"content-type", "etag", "last-modified", "content-length"}
)
_SEC_HISTORY_NAME = re.compile(
    r"^CIK\d{10}-submissions-\d{3}\.json$"
)
_SEC_ARCHIVE_URL = re.compile(
    r"^https://www\.sec\.gov/Archives/edgar/data/"
    r"(?P<cik>\d+)/(?P<accession>\d{18})/"
    r"(?P<document>[A-Za-z0-9][A-Za-z0-9._-]*)$"
)
_SEC_SUBMISSION_DOCUMENT = re.compile(
    r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$"
)
_CLINICAL_HISTORY_SUMMARY_URL = re.compile(
    r"^https://clinicaltrials\.gov/api/int/studies/"
    r"(?P<nct_id>NCT\d{8})\?history=true$"
)
_CLINICAL_HISTORY_VERSION_URL = re.compile(
    r"^https://clinicaltrials\.gov/api/int/studies/"
    r"(?P<nct_id>NCT\d{8})/history/(?P<version>\d+)$"
)
_ResponseT = TypeVar("_ResponseT")


class _Transport(Protocol[_ResponseT]):
    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> _ResponseT: ...


def _captured_headers(
    raw_headers: Mapping[str, str],
    *,
    body: bytes,
) -> dict[str, str]:
    if not isinstance(body, bytes):
        raise ValueError("captured response body is invalid")
    captured: dict[str, str] = {}
    for key, value in raw_headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("captured response headers are invalid")
        normalized_key = key.casefold()
        if normalized_key not in _CAPTURE_HEADERS:
            continue
        if normalized_key in captured:
            raise ValueError("captured response headers are ambiguous")
        captured[normalized_key] = value.strip()
    if "content-length" in captured:
        captured["content-length"] = str(len(body))
    return captured


@dataclass(frozen=True, slots=True)
class CapturedExchange:
    response_key: str
    route: Mapping[str, object]
    request_url: str
    final_url: str
    status: int
    headers: Mapping[str, str]
    retrieved_at: datetime
    body: bytes


@dataclass(frozen=True, slots=True)
class _RecordedResponse:
    request_url: str
    final_url: str
    status: int
    headers: Mapping[str, str]
    retrieved_at: datetime
    body: bytes
    response: object


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


def _json_object(
    response: _RecordedResponse,
    *,
    label: str,
) -> Mapping[str, object]:
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} response graph is invalid") from error
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise ValueError(f"{label} response graph is invalid")
    return value


def _column_pair(
    value: object,
    *,
    label: str,
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} response graph is invalid")
    accessions = value.get("accessionNumber")
    primary_documents = value.get("primaryDocument")
    if not isinstance(accessions, list) or not isinstance(
        primary_documents,
        list,
    ):
        raise ValueError(f"{label} response graph is invalid")
    if len(accessions) != len(primary_documents):
        raise ValueError(f"{label} response graph is invalid")
    result: list[tuple[str, str]] = []
    for accession, primary_document in zip(
        accessions,
        primary_documents,
        strict=True,
    ):
        if (
            not isinstance(accession, str)
            or re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) is None
            or not isinstance(primary_document, str)
            or _SEC_SUBMISSION_DOCUMENT.fullmatch(
                primary_document
            )
            is None
            or any(
                segment in {"", ".", ".."}
                for segment in primary_document.split("/")
            )
        ):
            raise ValueError(f"{label} response graph is invalid")
        result.append((accession, primary_document))
    return tuple(result)


class _ExhibitIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_manifest = False
        self._in_row = False
        self._in_cell = False
        self._cells: list[list[str]] = []
        self.manifest_count = 0
        self.rows: list[tuple[str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if tag == "table":
            self._in_manifest = (
                (attributes.get("summary") or "").strip().casefold()
                == "document format files"
            )
            if self._in_manifest:
                self.manifest_count += 1
        elif tag == "tr" and self._in_manifest:
            self._in_row = True
            self._cells = []
        elif tag == "td" and self._in_row:
            self._in_cell = True
            self._cells.append([])

    def handle_data(self, data: str) -> None:
        if self._in_cell and self._cells:
            self._cells[-1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            values = tuple(
                " ".join("".join(cell).split())
                for cell in self._cells
            )
            if len(values) >= 4 and values[3].upper().startswith(
                "EX-"
            ):
                document_name = values[2].split()[0]
                if re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9._-]*",
                    document_name,
                ) is not None:
                    self.rows.append(
                        (document_name, values[3].upper())
                    )
            self._in_row = False
        elif tag == "table" and self._in_manifest:
            self._in_manifest = False


class _RouteResolver:
    def __init__(
        self,
        plan: PrimarySourcePlan,
        responses: Mapping[str, _RecordedResponse],
    ) -> None:
        self._plan = plan
        self._responses = responses
        self._history_files, self._filing_documents = (
            self._sec_submission_graph()
        )
        self._filing_exhibits = self._sec_exhibit_graph()
        self._clinical_pages = self._clinical_page_graph()

    def _sec_submission_graph(
        self,
    ) -> tuple[frozenset[str], Mapping[str, str]]:
        root_url = (
            "https://data.sec.gov/submissions/"
            f"CIK{self._plan.loaded.cik}.json"
        )
        root = self._responses.get(root_url)
        if root is None:
            return frozenset(), {}
        payload = _json_object(root, label="SEC submissions")
        filings = payload.get("filings")
        if not isinstance(filings, Mapping):
            raise ValueError("SEC submissions response graph is invalid")
        pairs = list(
            _column_pair(
                filings.get("recent"),
                label="SEC submissions",
            )
        )
        raw_files = filings.get("files", [])
        if not isinstance(raw_files, list):
            raise ValueError("SEC submissions response graph is invalid")
        history_files: set[str] = set()
        for value in raw_files:
            if not isinstance(value, Mapping):
                raise ValueError(
                    "SEC submissions response graph is invalid"
                )
            name = value.get("name")
            if (
                not isinstance(name, str)
                or _SEC_HISTORY_NAME.fullmatch(name) is None
                or name in history_files
            ):
                raise ValueError(
                    "SEC submissions response graph is invalid"
                )
            history_files.add(name)
            history_url = (
                "https://data.sec.gov/submissions/"
                f"{name}"
            )
            history = self._responses.get(history_url)
            if history is not None:
                pairs.extend(
                    _column_pair(
                        _json_object(
                            history,
                            label="SEC submissions history",
                        ),
                        label="SEC submissions history",
                    )
                )
        filing_documents: dict[str, str] = {}
        for accession, primary_document in pairs:
            prior = filing_documents.get(accession)
            if prior is not None and prior != primary_document:
                raise ValueError(
                    "SEC submissions response graph is ambiguous"
                )
            filing_documents[accession] = primary_document
        return frozenset(history_files), filing_documents

    def _sec_exhibit_graph(
        self,
    ) -> Mapping[tuple[str, str], str]:
        exhibits: dict[tuple[str, str], str] = {}
        expected_cik = self._plan.loaded.cik.lstrip("0") or "0"
        for url, response in self._responses.items():
            archive = _SEC_ARCHIVE_URL.fullmatch(url)
            if (
                archive is None
                or archive.group("cik") != expected_cik
            ):
                continue
            compact_accession = archive.group("accession")
            accession = (
                compact_accession[:10]
                + "-"
                + compact_accession[10:12]
                + "-"
                + compact_accession[12:]
            )
            if (
                accession not in self._filing_documents
                or archive.group("document")
                != f"{accession}-index.html"
            ):
                continue
            try:
                text = response.body.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(
                    "SEC filing index response graph is invalid"
                ) from error
            parser = _ExhibitIndexParser()
            parser.feed(text)
            if parser.manifest_count != 1:
                raise ValueError(
                    "SEC filing index response graph is invalid"
                )
            for document_name, exhibit_type in parser.rows:
                key = (accession, document_name)
                prior = exhibits.get(key)
                if prior is not None and prior != exhibit_type:
                    raise ValueError(
                        "SEC filing index response graph is ambiguous"
                    )
                exhibits[key] = exhibit_type
        return exhibits

    def _clinical_page_graph(self) -> Mapping[str, int]:
        base_url = _clinical_base_url(self._plan)
        if base_url not in self._responses:
            return {}
        pages: dict[str, int] = {}
        current_url = base_url
        while True:
            if current_url in pages:
                raise ValueError(
                    "clinical trials response graph is ambiguous"
                )
            response = self._responses.get(current_url)
            if response is None:
                raise ValueError(
                    "clinical trials response graph is incomplete"
                )
            pages[current_url] = len(pages)
            payload = _json_object(
                response,
                label="clinical trials",
            )
            token = payload.get("nextPageToken")
            if token is None:
                return pages
            if not isinstance(token, str) or not token.strip():
                raise ValueError(
                    "clinical trials response graph is invalid"
                )
            current_url = (
                base_url
                + "&"
                + urlencode({"pageToken": token})
            )

    def resolve(
        self,
        response: _RecordedResponse,
    ) -> Mapping[str, object]:
        url = response.request_url
        candidates: list[dict[str, object]] = []
        cik = self._plan.loaded.cik
        exact_routes = {
            "https://www.sec.gov/files/company_tickers_exchange.json": {
                "role": "sec_security_registry",
            },
            f"https://data.sec.gov/submissions/CIK{cik}.json": {
                "role": "sec_submissions_root",
            },
            (
                "https://data.sec.gov/api/xbrl/companyfacts/"
                f"CIK{cik}.json"
            ): {"role": "sec_companyfacts"},
        }
        exact = exact_routes.get(url)
        if exact is not None:
            candidates.append(exact)
        history_prefix = "https://data.sec.gov/submissions/"
        if url.startswith(history_prefix):
            history_name = url[len(history_prefix) :]
            if history_name in self._history_files:
                candidates.append(
                    {
                        "role": "sec_submissions_history",
                        "history_file": history_name,
                    }
                )
        clinical_ordinal = self._clinical_pages.get(url)
        if clinical_ordinal is not None:
            candidates.append(
                {
                    "role": "clinical_trials_page",
                    "page_ordinal": clinical_ordinal,
                }
            )
        history_summary = _CLINICAL_HISTORY_SUMMARY_URL.fullmatch(
            url
        )
        if history_summary is not None:
            candidates.append(
                {
                    "role": "clinical_trials_history_summary",
                    "nct_id": history_summary.group("nct_id"),
                }
            )
        history_version = _CLINICAL_HISTORY_VERSION_URL.fullmatch(
            url
        )
        if history_version is not None:
            candidates.append(
                {
                    "role": "clinical_trials_history_version",
                    "nct_id": history_version.group("nct_id"),
                    "version": int(history_version.group("version")),
                }
            )
        for role, sources in (
            ("issuer_document", self._plan.issuer_sources),
            ("regulatory_document", self._plan.regulatory_sources),
        ):
            for source in sources:
                if source.source_url == url:
                    candidates.append(
                        {
                            "role": role,
                            "source_key": source.source_key,
                        }
                    )
        archive = _SEC_ARCHIVE_URL.fullmatch(url)
        if archive is not None and archive.group("cik") == (
            cik.lstrip("0") or "0"
        ):
            compact_accession = archive.group("accession")
            accession = (
                compact_accession[:10]
                + "-"
                + compact_accession[10:12]
                + "-"
                + compact_accession[12:]
            )
            document = archive.group("document")
            primary_document = self._filing_documents.get(accession)
            if document == primary_document:
                candidates.append(
                    {
                        "role": "sec_filing_document",
                        "accession_number": accession,
                        "primary_document": document,
                    }
                )
            if (
                accession in self._filing_documents
                and document == f"{accession}-index.html"
            ):
                candidates.append(
                    {
                        "role": "sec_filing_index",
                        "accession_number": accession,
                    }
                )
            exhibit_type = self._filing_exhibits.get(
                (accession, document)
            )
            if exhibit_type is not None:
                candidates.append(
                    {
                        "role": "sec_filing_exhibit",
                        "accession_number": accession,
                        "exhibit_type": exhibit_type,
                        "document_name": document,
                    }
                )
        unique_candidates = {
            json.dumps(
                candidate,
                sort_keys=True,
                separators=(",", ":"),
            ): candidate
            for candidate in candidates
        }
        if len(unique_candidates) != 1:
            state = (
                "unknown"
                if not unique_candidates
                else "ambiguous"
            )
            raise ValueError(f"capture response route is {state}")
        return next(iter(unique_candidates.values()))


class _PlanBoundRecordingTransport:
    def __init__(
        self,
        recorder: PrimarySourceCaptureRecorder,
        transport: _Transport,
    ) -> None:
        self._recorder = recorder
        self._transport = transport
        self._last_retrieved_at: datetime | None = None

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ):
        recorded = self._recorder._request(
            self._transport,
            url,
            headers=headers,
        )
        self._last_retrieved_at = recorded.retrieved_at
        return recorded.response

    def clock(self) -> datetime:
        if self._last_retrieved_at is None:
            raise RuntimeError("capture clock requested before response")
        return self._last_retrieved_at


class PrimarySourceCaptureRecorder:
    """Record live exchanges and infer routes from one bound source plan."""

    def __init__(
        self,
        *,
        source_plan: bytes,
        request: PrimarySourceRequest,
        trusted_issuer_hosts: tuple[str, ...],
        clock: Callable[[], datetime],
    ) -> None:
        self._source_plan = source_plan
        self._request_context = request
        self._trusted_issuer_hosts = trusted_issuer_hosts
        self._plan = bind_primary_source_plan(
            load_primary_source_plan(source_plan),
            request,
            trusted_issuer_hosts=trusted_issuer_hosts,
        )
        self._clock = clock
        self._responses: dict[str, _RecordedResponse] = {}
        self._lock = Lock()

    @property
    def plan(self) -> PrimarySourcePlan:
        return self._plan

    def transport(
        self,
        transport: _Transport[_ResponseT],
    ) -> _PlanBoundRecordingTransport:
        return _PlanBoundRecordingTransport(self, transport)

    def _request(
        self,
        transport: _Transport,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> _RecordedResponse:
        with self._lock:
            existing = self._responses.get(url)
            if existing is not None:
                return existing
            response = transport.request(url, headers=headers)
            retrieved_at = self._clock()
            if (
                retrieved_at.tzinfo is None
                or retrieved_at.utcoffset() is None
            ):
                raise ValueError(
                    "capture retrieval clock must include timezone"
                )
            final_url = getattr(response, "final_url", None)
            raw_headers = getattr(response, "headers", None)
            body = getattr(response, "body", None)
            status = getattr(response, "status", None)
            if not isinstance(final_url, str) or not final_url:
                raise ValueError("captured response final URL is required")
            if not isinstance(raw_headers, Mapping):
                raise ValueError("captured response headers are invalid")
            if (
                isinstance(status, bool)
                or not isinstance(status, int)
                or not isinstance(body, bytes)
            ):
                raise ValueError("captured response is invalid")
            captured_headers = _captured_headers(
                raw_headers,
                body=body,
            )
            recorded = _RecordedResponse(
                request_url=url,
                final_url=final_url,
                status=status,
                headers=captured_headers,
                retrieved_at=retrieved_at.astimezone(UTC),
                body=body,
                response=response,
            )
            self._responses[url] = recorded
            return recorded

    def assemble(
        self,
        *,
        capture_id: str,
        revision: int,
        assembled_at: datetime,
    ) -> bytes:
        resolver = _RouteResolver(self._plan, self._responses)
        exchanges = tuple(
            self._resolved_exchange(
                response,
                route=resolver.resolve(response),
            )
            for response in self._responses.values()
        )
        keys = tuple(exchange.response_key for exchange in exchanges)
        if len(keys) != len(set(keys)):
            raise ValueError("capture response route is ambiguous")
        return assemble_primary_source_capture_archive(
            exchanges=exchanges,
            source_plan=self._source_plan,
            request=self._request_context,
            trusted_issuer_hosts=self._trusted_issuer_hosts,
            capture_id=capture_id,
            revision=revision,
            assembled_at=assembled_at,
        )

    def _resolved_exchange(
        self,
        response: _RecordedResponse,
        *,
        route: Mapping[str, object],
    ) -> CapturedExchange:
        route_bytes = json.dumps(
            route,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        response_key = (
            f"{route['role']}-"
            f"{hashlib.sha256(route_bytes).hexdigest()[:24]}"
        )
        return CapturedExchange(
            response_key=response_key,
            route=dict(route),
            request_url=response.request_url,
            final_url=response.final_url,
            status=response.status,
            headers=response.headers,
            retrieved_at=response.retrieved_at,
            body=response.body,
        )


class _RecordingTransport:
    def __init__(
        self,
        recorder: PrimarySourceExchangeRecorder,
        transport: _Transport,
        *,
        route_for_response: Callable[
            [str, object],
            tuple[str, Mapping[str, object]],
        ],
        clock: Callable[[], datetime],
    ) -> None:
        self._recorder = recorder
        self._transport = transport
        self._route_for_response = route_for_response
        self._clock = clock
        self._last_retrieved_at: datetime | None = None

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ):
        response = self._transport.request(url, headers=headers)
        retrieved_at = self._clock()
        if (
            retrieved_at.tzinfo is None
            or retrieved_at.utcoffset() is None
        ):
            raise ValueError("capture retrieval clock must include timezone")
        retrieved_at = retrieved_at.astimezone(UTC)
        response_key, route = self._route_for_response(url, response)
        final_url = getattr(response, "final_url", None)
        if not isinstance(final_url, str) or not final_url:
            raise ValueError("captured response final URL is required")
        raw_headers = getattr(response, "headers", None)
        if not isinstance(raw_headers, Mapping):
            raise ValueError("captured response headers are invalid")
        body = getattr(response, "body", None)
        captured_headers = _captured_headers(
            raw_headers,
            body=body,
        )
        exchange = CapturedExchange(
            response_key=response_key,
            route=dict(route),
            request_url=url,
            final_url=final_url,
            status=getattr(response, "status"),
            headers=captured_headers,
            retrieved_at=retrieved_at,
            body=body,
        )
        self._recorder._append(exchange)
        self._last_retrieved_at = retrieved_at
        return response

    def clock(self) -> datetime:
        if self._last_retrieved_at is None:
            raise RuntimeError("capture clock requested before response")
        return self._last_retrieved_at


class PrimarySourceExchangeRecorder:
    def __init__(self) -> None:
        self._exchanges: list[CapturedExchange] = []
        self._response_keys: set[str] = set()
        self._request_urls: set[str] = set()

    @property
    def exchanges(self) -> tuple[CapturedExchange, ...]:
        return tuple(self._exchanges)

    def transport(
        self,
        transport: _Transport[_ResponseT],
        *,
        route_for_response: Callable[
            [str, object],
            tuple[str, Mapping[str, object]],
        ],
        clock: Callable[[], datetime],
    ) -> _RecordingTransport:
        return _RecordingTransport(
            self,
            transport,
            route_for_response=route_for_response,
            clock=clock,
        )

    def _append(self, exchange: CapturedExchange) -> None:
        if exchange.response_key in self._response_keys:
            raise ValueError("capture response key must be unique")
        if exchange.request_url in self._request_urls:
            raise ValueError("capture request URL must be unique")
        self._response_keys.add(exchange.response_key)
        self._request_urls.add(exchange.request_url)
        self._exchanges.append(exchange)


def assemble_primary_source_capture_archive(
    *,
    exchanges: tuple[CapturedExchange, ...],
    source_plan: bytes,
    request: PrimarySourceRequest,
    trusted_issuer_hosts: tuple[str, ...],
    capture_id: str,
    revision: int,
    assembled_at: datetime,
) -> bytes:
    if not exchanges:
        raise ValueError("capture exchanges must not be empty")
    if assembled_at.tzinfo is None or assembled_at.utcoffset() is None:
        raise ValueError("capture assembly time must include timezone")
    assembled_at = assembled_at.astimezone(UTC)
    if any(
        exchange.retrieved_at.tzinfo is None
        or exchange.retrieved_at.utcoffset() is None
        or exchange.retrieved_at.astimezone(UTC) > assembled_at
        for exchange in exchanges
    ):
        raise ValueError("capture retrieval time is invalid")
    plan = bind_primary_source_plan(
        load_primary_source_plan(source_plan),
        request,
        trusted_issuer_hosts=trusted_issuer_hosts,
    )
    payloads: dict[str, bytes] = {}
    responses: list[dict[str, object]] = []
    for exchange in exchanges:
        body_sha256 = hashlib.sha256(exchange.body).hexdigest()
        body_path = f"payloads/{body_sha256}.bin"
        payloads[body_path] = exchange.body
        responses.append(
            {
                "response_key": exchange.response_key,
                "route": dict(exchange.route),
                "request_url": exchange.request_url,
                "final_url": exchange.final_url,
                "status": exchange.status,
                "headers": _captured_headers(
                    exchange.headers,
                    body=exchange.body,
                ),
                "retrieved_at": exchange.retrieved_at.astimezone(
                    UTC
                ).isoformat(),
                "body": {
                    "path": body_path,
                    "byte_length": len(exchange.body),
                    "sha256": body_sha256,
                },
            }
        )
    manifest = {
        "contract_version": CAPTURE_CONTRACT_VERSION,
        "capture_id": capture_id,
        "revision": revision,
        "provenance_mode": "operator_supplied_unverified",
        "assembled_at": assembled_at.isoformat(),
        "context": {
            "operator_id": request.operator_id,
            "security_id": request.security_id,
            "cik": request.cik,
            "issuer_name": request.issuer_name,
            "primary_listing_exchange": request.primary_listing_exchange,
            "as_of_cutoff": request.as_of_cutoff.isoformat(),
            "question_type": plan.loaded.question_type,
            "workflow_config_version": (
                plan.loaded.workflow_config_version
            ),
        },
        "plan": {
            "path": "primary-source-plan.json",
            "plan_id": plan.loaded.plan_id,
            "revision": plan.loaded.revision,
            "content_hash": plan.content_hash,
        },
        "responses": sorted(
            responses,
            key=lambda response: (
                str(response["route"].get("role")),
                str(response["response_key"]),
                str(response["request_url"]),
            ),
        ),
    }
    entries = {
        "capture.json": json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
        "primary-source-plan.json": source_plan,
        **payloads,
    }
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        for path in sorted(entries):
            info = ZipInfo(
                path,
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.compress_type = ZIP_STORED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, entries[path])
    return output.getvalue()


__all__ = [
    "CapturedExchange",
    "PrimarySourceCaptureRecorder",
    "PrimarySourceExchangeRecorder",
    "assemble_primary_source_capture_archive",
]
