from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from workers.primary_sources.captures import (
    PrimarySourceCaptureError,
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
        try:
            capture = load_primary_source_capture(
                raw_archive,
                request=PrimarySourceRequest(
                    operator_id=request.operator_id,
                    security_id=request.security_id,
                    cik=request.cik,
                    issuer_name=request.issuer_name,
                    primary_listing_exchange=request.primary_listing_exchange,
                    as_of_cutoff=request.as_of_cutoff,
                ),
                trusted_issuer_hosts=request.trusted_issuer_hosts,
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
    "MAX_CAPTURE_ARCHIVE_BYTES",
]
