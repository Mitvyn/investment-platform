"""Desktop-local Research Run command composition and bounded execution.

This module owns only local file repositories and deterministic replay. It
never starts a provider, model, hosted, or network transport. Responses expose
sanitized local receipt/progress records; lease tokens and archive contents
stay inside the worker.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

from investment_research_os.evidence_bundles.file_storage import (
    FileEvidenceBundleRepository,
)
from investment_research_os.research_runs.file_storage import (
    FileResearchRunRepository,
)
from workers.primary_sources.plans import (
    PrimarySourcePlanError,
    load_primary_source_plan,
)
from workers.primary_sources.storage import (
    FilePrimarySourceCaptureRepository,
)
from workers.research_committee.local_commands import (
    FileResearchRunCommandStore,
    LocalCommandStoreError,
    LocalResearchRunCommand,
)
from workers.research_committee.local_execution import (
    MAXIMUM_BOUNDED_STAGES,
    LocalExecutionError,
    compose_local_research_command_executor,
)


EMBEDDED_PLAN_ENTRY = "primary-source-plan.json"
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")


class DesktopResearchRunError(ValueError):
    """Raised when desktop-local Research Run state cannot be served safely."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DesktopResearchRunRequest:
    operator_id: str
    security_id: str
    ticker: str
    question_type_version: str
    workflow_config_version: str
    as_of_cutoff: datetime
    operator_focus: str | None
    capture_id: str
    capture_revision: int
    capture_content_hash: str


class DesktopResearchRunService:
    """Own one local command store per authenticated operator."""

    def __init__(
        self,
        *,
        capture_repository: FilePrimarySourceCaptureRepository,
        command_root: Path,
        research_run_root: Path,
        evidence_bundle_root: Path,
        sec_user_agent: str,
        clock: Callable[[], datetime],
    ) -> None:
        if not sec_user_agent.strip():
            raise ValueError("SEC user agent is required")
        self._captures = capture_repository
        self._command_root = Path(command_root)
        self._research_run_root = Path(research_run_root)
        self._evidence_bundle_root = Path(evidence_bundle_root)
        self._sec_user_agent = sec_user_agent
        self._clock = clock

    def enqueue_and_execute(
        self,
        request: DesktopResearchRunRequest,
    ) -> dict[str, object]:
        normalized = self._validate_request(request)
        commands = self._commands(normalized.operator_id)
        self._validate_capture(normalized)
        hosts = self._issuer_hosts(normalized)
        try:
            receipt = commands.enqueue(
                security_id=normalized.security_id,
                as_of_cutoff=normalized.as_of_cutoff,
                operator_focus=normalized.operator_focus,
                question_type_version=normalized.question_type_version,
                workflow_config_version=normalized.workflow_config_version,
                capture_id=normalized.capture_id,
                capture_revision=normalized.capture_revision,
                capture_content_hash=normalized.capture_content_hash,
            )
            executor = compose_local_research_command_executor(
                worker_id="iros-desktop-research-worker",
                commands=commands,
                research_run_repository=FileResearchRunRepository(
                    self._research_run_root
                ),
                evidence_bundle_repository=FileEvidenceBundleRepository(
                    self._evidence_bundle_root
                ),
                capture_repository=self._captures,
                ticker=normalized.ticker,
                trusted_issuer_hosts=hosts,
                sec_user_agent=self._sec_user_agent,
                clock=self._clock,
            )
            executor.run_bounded(max_stages=MAXIMUM_BOUNDED_STAGES)
        except DesktopResearchRunError:
            raise
        except (LocalCommandStoreError, LocalExecutionError, OSError, ValueError) as error:
            raise DesktopResearchRunError(
                "research_run_local_execution_unavailable"
            ) from error
        return self._response(commands, receipt.command_id)

    def load(self, *, operator_id: str, command_id: str) -> dict[str, object] | None:
        try:
            normalized_operator = _uuid(operator_id, "operator identity")
            normalized_command = _uuid(command_id, "command identity")
            commands = self._commands(normalized_operator)
            if commands.get(normalized_command) is None:
                return None
            return self._response(commands, normalized_command)
        except (LocalCommandStoreError, OSError, ValueError) as error:
            raise DesktopResearchRunError(
                "research_run_local_state_unavailable"
            ) from error

    def _commands(self, operator_id: str) -> FileResearchRunCommandStore:
        return FileResearchRunCommandStore(
            self._command_root,
            operator_id=operator_id,
            clock=self._clock,
        )

    def _validate_capture(self, request: DesktopResearchRunRequest) -> None:
        capture = self._captures.get_capture(
            request.operator_id,
            request.capture_id,
            request.capture_revision,
        )
        if capture is None or (
            capture.operator_id != request.operator_id
            or capture.security_id != request.security_id
            or capture.as_of_cutoff != request.as_of_cutoff
            or capture.question_type_version != request.question_type_version
            or capture.workflow_config_version != request.workflow_config_version
            or capture.capture_content_hash != request.capture_content_hash
        ):
            raise DesktopResearchRunError("research_run_capture_unavailable")

    def _issuer_hosts(self, request: DesktopResearchRunRequest) -> tuple[str, ...]:
        try:
            archive = self._captures.read_archive(
                request.operator_id,
                request.capture_id,
                request.capture_revision,
            )
            with ZipFile(BytesIO(archive)) as entries:
                info = entries.getinfo(EMBEDDED_PLAN_ENTRY)
                if info.is_dir() or (info.external_attr >> 16) & 0o120000 == 0o120000:
                    raise PrimarySourcePlanError("embedded source plan entry is invalid")
                plan = load_primary_source_plan(entries.read(info))
        except (BadZipFile, KeyError, OSError, PrimarySourcePlanError) as error:
            raise DesktopResearchRunError("research_run_capture_invalid") from error
        hosts = tuple(
            sorted(
                {
                    str(urlsplit(source.source_url).hostname).casefold()
                    for source in plan.issuer_sources
                    if urlsplit(source.source_url).hostname
                }
            )
        )
        if not hosts:
            raise DesktopResearchRunError("research_run_issuer_hosts_unavailable")
        return hosts

    @staticmethod
    def _validate_request(
        request: DesktopResearchRunRequest,
    ) -> DesktopResearchRunRequest:
        if not isinstance(request, DesktopResearchRunRequest):
            raise DesktopResearchRunError("research_run_request_invalid")
        try:
            operator_id = _uuid(request.operator_id, "operator identity")
            security_id = _uuid(request.security_id, "security identity")
            capture_id = _uuid(request.capture_id, "capture identity")
        except ValueError as error:
            raise DesktopResearchRunError("research_run_request_invalid") from error
        ticker = request.ticker.strip().upper()
        if _TICKER.fullmatch(ticker) is None:
            raise DesktopResearchRunError("research_run_request_invalid")
        if request.as_of_cutoff.tzinfo is None or request.as_of_cutoff.utcoffset() is None:
            raise DesktopResearchRunError("research_run_request_invalid")
        return DesktopResearchRunRequest(
            operator_id=operator_id,
            security_id=security_id,
            ticker=ticker,
            question_type_version=request.question_type_version,
            workflow_config_version=request.workflow_config_version,
            as_of_cutoff=request.as_of_cutoff,
            operator_focus=request.operator_focus,
            capture_id=capture_id,
            capture_revision=request.capture_revision,
            capture_content_hash=request.capture_content_hash,
        )

    @staticmethod
    def _response(
        commands: FileResearchRunCommandStore,
        command_id: str,
    ) -> dict[str, object]:
        receipt: LocalResearchRunCommand | None = commands.get(command_id)
        progress = commands.progress(command_id)
        if receipt is None or progress is None:
            raise DesktopResearchRunError("research_run_local_state_unavailable")
        return {
            "contract_version": "research_run_local_command_response.v1",
            "receipt": receipt.as_dict(),
            "progress": progress,
        }


def _uuid(value: object, label: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"{label} is invalid") from error


__all__ = [
    "DesktopResearchRunError",
    "DesktopResearchRunRequest",
    "DesktopResearchRunService",
]
