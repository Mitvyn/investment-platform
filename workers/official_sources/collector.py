from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit

from workers.ids import stable_id
from workers.primary_sources.models import PrimarySourceRequest
from workers.primary_sources.temporal import assess_publication_time

from .models import (
    OfficialBytesResponse,
    OfficialPassage,
    OfficialSourceCoverageResult,
    OfficialSourceDocument,
    OfficialSourceLocator,
    OfficialSourceResult,
    OfficialSourceSnapshot,
)


class OfficialBytesTransport(Protocol):
    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> OfficialBytesResponse: ...


class OfficialSourceIntegrityError(RuntimeError):
    """Raised when an official source cannot satisfy provenance checks."""


class OfficialEvidenceAdapter:
    def __init__(
        self,
        *,
        source_class: str,
        allowed_hosts: tuple[str, ...],
        transport: OfficialBytesTransport,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.source_class = source_class
        self.allowed_hosts = tuple(host.lower() for host in allowed_hosts)
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(UTC))

    def collect(
        self,
        request: PrimarySourceRequest,
        locators: tuple[OfficialSourceLocator, ...],
    ) -> OfficialSourceSnapshot:
        if not locators:
            raise OfficialSourceIntegrityError("at least one locator is required")
        source_keys = tuple(locator.source_key for locator in locators)
        if len(source_keys) != len(set(source_keys)):
            raise OfficialSourceIntegrityError("official source keys must be unique")
        requirements = {locator.requirement_id for locator in locators}
        for requirement_id in requirements:
            matching_locators = tuple(
                locator
                for locator in locators
                if locator.requirement_id == requirement_id
            )
            if not any(
                locator.coverage_role == "required" for locator in matching_locators
            ):
                raise OfficialSourceIntegrityError(
                    "official source requirement needs at least one required locator"
                )
            coverage_modes = {locator.coverage_mode for locator in matching_locators}
            if len(coverage_modes) != 1:
                raise OfficialSourceIntegrityError(
                    "official source coverage modes must agree within a requirement"
                )
        ordered_locators = tuple(
            sorted(
                locators,
                key=lambda locator: (
                    locator.requirement_id,
                    locator.source_key,
                    locator.source_url,
                ),
            )
        )
        source_results = tuple(
            self._collect_one(request, locator) for locator in ordered_locators
        )
        coverage_results = self._coverage_results(source_results)
        return OfficialSourceSnapshot(
            operator_id=request.operator_id,
            security_id=request.security_id,
            cik=request.cik,
            issuer_name=request.issuer_name,
            as_of_cutoff=request.as_of_cutoff,
            source_class=self.source_class,
            source_results=source_results,
            coverage_state=(
                "complete"
                if coverage_results
                and all(result.state == "complete" for result in coverage_results)
                else "incomplete"
            ),
            coverage_results=coverage_results,
        )

    def _collect_one(
        self,
        request: PrimarySourceRequest,
        locator: OfficialSourceLocator,
    ) -> OfficialSourceResult:
        self._require_allowed_origin(
            locator.source_url,
            context="source URL",
        )
        publication = assess_publication_time(
            locator.publication_time,
            request.as_of_cutoff,
        )
        if not publication.valid_at_cutoff:
            state = {
                "after_cutoff": "after_cutoff",
                "unavailable": "unavailable",
            }.get(publication.state, "ambiguous")
            return OfficialSourceResult(
                source_key=locator.source_key,
                requirement_id=locator.requirement_id,
                coverage_role=locator.coverage_role,
                coverage_mode=locator.coverage_mode,
                source_url=locator.source_url,
                state=state,
                reason_code=publication.reason_code,
                document=None,
                passages=(),
            )
        if (
            locator.effective_date is not None
            and locator.effective_date > request.as_of_cutoff.date()
        ):
            return OfficialSourceResult(
                source_key=locator.source_key,
                requirement_id=locator.requirement_id,
                coverage_role=locator.coverage_role,
                coverage_mode=locator.coverage_mode,
                source_url=locator.source_url,
                state="after_cutoff",
                reason_code="effective_date_after_cutoff",
                document=None,
                passages=(),
            )
        response = self.transport.request(
            locator.source_url,
            headers={
                "Accept": (
                    "application/json,text/html,"
                    "application/xhtml+xml,text/plain"
                    if self.source_class == "regulatory"
                    else "text/html,application/xhtml+xml,text/plain"
                ),
            },
        )
        if response.final_url is None:
            raise OfficialSourceIntegrityError(
                "official final response origin is not allowed"
            )
        self._require_allowed_origin(
            response.final_url,
            context="final response",
        )
        if not 200 <= response.status < 300:
            return OfficialSourceResult(
                source_key=locator.source_key,
                requirement_id=locator.requirement_id,
                coverage_role=locator.coverage_role,
                coverage_mode=locator.coverage_mode,
                source_url=locator.source_url,
                state="unavailable",
                reason_code="official_source_http_unavailable",
                document=None,
                passages=(),
            )
        content_type = next(
            (
                value
                for key, value in response.headers.items()
                if key.lower() == "content-type"
            ),
            "",
        )
        media_type = content_type.partition(";")[0].strip().lower()
        permitted_media = {
            "text/html",
            "application/xhtml+xml",
            "text/plain",
        }
        if self.source_class == "regulatory":
            permitted_media.add("application/json")
        if media_type not in permitted_media:
            raise OfficialSourceIntegrityError(
                "official source content type is invalid"
            )
        try:
            content_text = response.body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise OfficialSourceIntegrityError(
                "official source document is not valid UTF-8"
            ) from error
        if not content_text.strip():
            raise OfficialSourceIntegrityError("official source document is empty")
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise OfficialSourceIntegrityError(
                "official source retrieval clock must include timezone"
            )
        retrieved_at = retrieved_at.astimezone(UTC)
        content_sha256 = hashlib.sha256(response.body).hexdigest()
        document_id = stable_id(
            request.operator_id,
            "official_source_document",
            (
                f"{request.security_id}:{self.source_class}:"
                f"{response.final_url}:"
                f"{content_sha256}"
            ),
        )
        document = OfficialSourceDocument(
            document_id=document_id,
            source_key=locator.source_key,
            source_class=self.source_class,
            title=locator.title,
            source_url=locator.source_url,
            final_url=response.final_url or locator.source_url,
            publication_state=publication.state,
            publication_reason_code=publication.reason_code,
            published_at=publication.published_at,
            publication_date=publication.publication_date,
            effective_date=locator.effective_date,
            retrieved_at=retrieved_at,
            content_sha256=content_sha256,
            content_text=content_text,
        )
        passage_counts = tuple(
            content_text.count(passage.exact_text) for passage in locator.passages
        )
        if any(count > 1 for count in passage_counts):
            return OfficialSourceResult(
                source_key=locator.source_key,
                requirement_id=locator.requirement_id,
                coverage_role=locator.coverage_role,
                coverage_mode=locator.coverage_mode,
                source_url=locator.source_url,
                state="ambiguous",
                reason_code="exact_passage_ambiguous",
                document=document,
                passages=(),
            )
        if any(count == 0 for count in passage_counts):
            return OfficialSourceResult(
                source_key=locator.source_key,
                requirement_id=locator.requirement_id,
                coverage_role=locator.coverage_role,
                coverage_mode=locator.coverage_mode,
                source_url=locator.source_url,
                state="unavailable",
                reason_code="exact_passage_unavailable",
                document=document,
                passages=(),
            )
        passages = tuple(
            OfficialPassage(
                passage_id=stable_id(
                    request.operator_id,
                    "official_source_passage",
                    (
                        f"{document_id}:{passage.passage_key}:"
                        f"{hashlib.sha256(passage.exact_text.encode()).hexdigest()}"
                    ),
                ),
                document_id=document_id,
                passage_key=passage.passage_key,
                locator=passage.locator,
                passage_text=passage.exact_text,
                passage_sha256=hashlib.sha256(passage.exact_text.encode()).hexdigest(),
            )
            for passage in locator.passages
        )
        return OfficialSourceResult(
            source_key=locator.source_key,
            requirement_id=locator.requirement_id,
            coverage_role=locator.coverage_role,
            coverage_mode=locator.coverage_mode,
            source_url=locator.source_url,
            state="available",
            reason_code="official_source_collected",
            document=document,
            passages=passages,
        )

    @staticmethod
    def _coverage_results(
        source_results: tuple[OfficialSourceResult, ...],
    ) -> tuple[OfficialSourceCoverageResult, ...]:
        requirements = sorted({result.requirement_id for result in source_results})
        coverage_results: list[OfficialSourceCoverageResult] = []
        for requirement_id in requirements:
            matching = tuple(
                result
                for result in source_results
                if result.requirement_id == requirement_id
            )
            collected = tuple(
                sorted(
                    result.source_key
                    for result in matching
                    if result.state == "available"
                )
            )
            coverage_mode = matching[0].coverage_mode
            required_source_keys = tuple(
                sorted(
                    result.source_key
                    for result in matching
                    if result.coverage_role == "required"
                )
            )
            optional_source_keys = tuple(
                sorted(
                    result.source_key
                    for result in matching
                    if result.coverage_role == "optional"
                )
            )
            unresolved_required = tuple(
                sorted(
                    result.source_key
                    for result in matching
                    if result.coverage_role == "required"
                    and result.state != "available"
                )
            )
            unresolved_optional = tuple(
                sorted(
                    result.source_key
                    for result in matching
                    if result.coverage_role == "optional"
                    and result.state != "available"
                )
            )
            collected_required = set(required_source_keys).intersection(collected)
            if not required_source_keys:
                complete = False
            elif coverage_mode == "all":
                complete = not unresolved_required
            else:
                complete = bool(collected_required)
            coverage_results.append(
                OfficialSourceCoverageResult(
                    requirement_id=requirement_id,
                    coverage_mode=coverage_mode,
                    state="complete" if complete else "incomplete",
                    required_source_keys=required_source_keys,
                    optional_source_keys=optional_source_keys,
                    collected_source_keys=collected,
                    unresolved_required_source_keys=unresolved_required,
                    unresolved_optional_source_keys=unresolved_optional,
                    reason_codes=tuple(
                        sorted(
                            {
                                result.reason_code
                                for result in matching
                                if result.state != "available"
                            }
                        )
                    ),
                )
            )
        return tuple(coverage_results)

    def _require_allowed_origin(
        self,
        source_url: str,
        *,
        context: str,
    ) -> None:
        try:
            parsed = urlsplit(source_url)
            port = parsed.port
        except ValueError as error:
            raise OfficialSourceIntegrityError(
                f"official {context} origin is not allowed"
            ) from error
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.hostname.lower() not in self.allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
        ):
            raise OfficialSourceIntegrityError(
                f"official {context} origin is not allowed"
            )


class OfficialIssuerEvidenceAdapter(OfficialEvidenceAdapter):
    def __init__(
        self,
        *,
        allowed_hosts: tuple[str, ...],
        transport: OfficialBytesTransport,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(
            source_class="issuer",
            allowed_hosts=allowed_hosts,
            transport=transport,
            clock=clock,
        )


__all__ = [
    "OfficialBytesTransport",
    "OfficialEvidenceAdapter",
    "OfficialIssuerEvidenceAdapter",
    "OfficialSourceIntegrityError",
]
