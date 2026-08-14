from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from workers.primary_sources.storage import PersistedPrimarySourceCapture


@dataclass(frozen=True, slots=True)
class AcceptedCaptureCatalogEntry:
    capture_id: str
    capture_revision: int
    capture_content_hash: str
    as_of_cutoff: datetime
    question_type: str
    question_type_version: str
    workflow_config_version: str
    accepted_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted_at": self.accepted_at.isoformat(),
            "as_of_cutoff": self.as_of_cutoff.isoformat(),
            "capture_content_hash": self.capture_content_hash,
            "capture_id": self.capture_id,
            "capture_revision": self.capture_revision,
            "question_type": self.question_type,
            "question_type_version": self.question_type_version,
            "workflow_config_version": self.workflow_config_version,
        }


@dataclass(frozen=True, slots=True)
class AcceptedCaptureCatalog:
    captures: tuple[AcceptedCaptureCatalogEntry, ...]

    @property
    def capture_count(self) -> int:
        return len(self.captures)

    def as_dict(self) -> dict[str, object]:
        return {
            "capture_count": self.capture_count,
            "captures": [capture.as_dict() for capture in self.captures],
            "contract_version": "accepted_research_capture_list.v1",
        }


class AcceptedCaptureCatalogRepository(Protocol):
    def list_captures(
        self,
        operator_id: str,
        security_id: str,
        *,
        question_type_version: str | None = None,
        workflow_config_version: str | None = None,
        as_of_cutoff: datetime | None = None,
        max_count: int = 50,
    ) -> tuple[PersistedPrimarySourceCapture, ...]: ...


class DesktopResearchCaptureCatalog:
    """Maps private accepted-capture storage to sanitized desktop receipts."""

    def __init__(self, repository: AcceptedCaptureCatalogRepository) -> None:
        self._repository = repository

    def list_captures(
        self,
        *,
        operator_id: str,
        security_id: str,
        question_type_version: str | None = None,
        workflow_config_version: str | None = None,
        as_of_cutoff: datetime | None = None,
        max_count: int = 50,
    ) -> AcceptedCaptureCatalog:
        captures = self._repository.list_captures(
            operator_id,
            security_id,
            question_type_version=question_type_version,
            workflow_config_version=workflow_config_version,
            as_of_cutoff=as_of_cutoff,
            max_count=max_count,
        )
        return AcceptedCaptureCatalog(
            captures=tuple(_catalog_entry(capture) for capture in captures)
        )


def _catalog_entry(
    capture: PersistedPrimarySourceCapture,
) -> AcceptedCaptureCatalogEntry:
    return AcceptedCaptureCatalogEntry(
        capture_id=capture.capture_id,
        capture_revision=capture.capture_revision,
        capture_content_hash=capture.capture_content_hash,
        as_of_cutoff=capture.as_of_cutoff,
        question_type=capture.question_type,
        question_type_version=capture.question_type_version,
        workflow_config_version=capture.workflow_config_version,
        accepted_at=capture.accepted_at,
    )


__all__ = [
    "AcceptedCaptureCatalog",
    "AcceptedCaptureCatalogEntry",
    "AcceptedCaptureCatalogRepository",
    "DesktopResearchCaptureCatalog",
]
