from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from workers.primary_sources.captures import (
    PrimarySourceCaptureError,
    inspect_primary_source_capture_archive,
    load_primary_source_capture,
)
from workers.primary_sources.models import PrimarySourceRequest
from workers.primary_sources.storage import (
    FilePrimarySourceCaptureRepository,
    PersistedPrimarySourceCapture,
    PrimarySourceStorageError,
)

MAX_CAPTURE_ARCHIVE_BYTES = 25_000_000


class DesktopCaptureImportError(ValueError):
    """Raised when an operator-supplied capture archive import is rejected."""


@dataclass(frozen=True, slots=True)
class DesktopCaptureImportRequest:
    operator_id: str
    security_id: str
    cik: str
    issuer_name: str
    primary_listing_exchange: str
    as_of_cutoff: datetime
    archive_path: Path
    trusted_issuer_hosts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DesktopCaptureUploadRequest:
    operator_id: str
    security_id: str
    cik: str
    issuer_name: str
    primary_listing_exchange: str
    raw_archive: bytes
    confirm_embedded_issuer_hosts: bool


class DesktopCaptureImportService:
    """Imports an already collected, bounded primary-source capture archive.

    This never acquires sources, scrapes, or calls a provider. It replays and
    validates bytes already on local disk against the embedded plan and exact
    request identity, then persists through the existing immutable, no-clobber
    capture repository.
    """

    def __init__(
        self,
        repository: FilePrimarySourceCaptureRepository,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._clock = clock

    def import_capture(
        self, request: DesktopCaptureImportRequest
    ) -> PersistedPrimarySourceCapture:
        path = request.archive_path
        if not path.is_absolute():
            raise DesktopCaptureImportError("capture archive path must be absolute")
        if path.is_symlink() or not path.is_file():
            raise DesktopCaptureImportError("capture archive path is invalid")
        if not request.trusted_issuer_hosts or any(
            not host.strip() for host in request.trusted_issuer_hosts
        ):
            raise DesktopCaptureImportError("trusted issuer hosts are required")
        try:
            size = path.stat().st_size
            if size <= 0 or size > MAX_CAPTURE_ARCHIVE_BYTES:
                raise DesktopCaptureImportError("capture archive size is invalid")
            raw_archive = path.read_bytes()
        except OSError as error:
            raise DesktopCaptureImportError(
                "capture archive path is unreadable"
            ) from error
        return self._import_bytes(
            raw_archive,
            operator_id=request.operator_id,
            security_id=request.security_id,
            cik=request.cik,
            issuer_name=request.issuer_name,
            primary_listing_exchange=request.primary_listing_exchange,
            as_of_cutoff=request.as_of_cutoff,
            trusted_issuer_hosts=request.trusted_issuer_hosts,
        )

    def import_uploaded_capture(
        self, request: DesktopCaptureUploadRequest
    ) -> PersistedPrimarySourceCapture:
        if not isinstance(request.raw_archive, bytes):
            raise DesktopCaptureImportError("capture archive bytes are invalid")
        if not request.raw_archive or len(request.raw_archive) > MAX_CAPTURE_ARCHIVE_BYTES:
            raise DesktopCaptureImportError("capture archive size is invalid")
        if not request.confirm_embedded_issuer_hosts:
            raise DesktopCaptureImportError(
                "embedded issuer hosts require confirmation"
            )
        try:
            metadata = inspect_primary_source_capture_archive(request.raw_archive)
        except (PrimarySourceCaptureError, ValueError) as error:
            raise DesktopCaptureImportError(str(error)) from error
        if metadata.operator_id != request.operator_id:
            raise DesktopCaptureImportError("capture operator identity does not match")
        return self._import_bytes(
            request.raw_archive,
            operator_id=request.operator_id,
            security_id=request.security_id,
            cik=request.cik,
            issuer_name=request.issuer_name,
            primary_listing_exchange=request.primary_listing_exchange,
            as_of_cutoff=metadata.as_of_cutoff,
            trusted_issuer_hosts=metadata.trusted_issuer_hosts,
        )

    def _import_bytes(
        self,
        raw_archive: bytes,
        *,
        operator_id: str,
        security_id: str,
        cik: str,
        issuer_name: str,
        primary_listing_exchange: str,
        as_of_cutoff: datetime,
        trusted_issuer_hosts: tuple[str, ...],
    ) -> PersistedPrimarySourceCapture:
        try:
            capture = load_primary_source_capture(
                raw_archive,
                request=PrimarySourceRequest(
                    operator_id=operator_id,
                    security_id=security_id,
                    cik=cik,
                    issuer_name=issuer_name,
                    primary_listing_exchange=primary_listing_exchange,
                    as_of_cutoff=as_of_cutoff,
                ),
                trusted_issuer_hosts=trusted_issuer_hosts,
                accepted_at=self._clock,
            )
        except (PrimarySourceCaptureError, ValueError) as error:
            raise DesktopCaptureImportError(str(error)) from error
        try:
            return self._repository.save_capture(capture, raw_archive)
        except PrimarySourceStorageError as error:
            raise DesktopCaptureImportError(str(error)) from error


__all__ = [
    "DesktopCaptureImportError",
    "DesktopCaptureImportRequest",
    "DesktopCaptureImportService",
    "DesktopCaptureUploadRequest",
    "MAX_CAPTURE_ARCHIVE_BYTES",
]
