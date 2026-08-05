from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from uuid import UUID

from investment_research_os.research_runs import ResearchRun

from .captures import (
    PrimarySourceCapture,
    PrimarySourceCaptureError,
    load_primary_source_capture,
)
from .models import PrimarySourceRequest


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_METADATA_VERSION = "primary_source_capture_storage.v1"


class PrimarySourceStorageError(ValueError):
    """Raised when durable capture state violates immutable identity."""


@dataclass(frozen=True, slots=True)
class PersistedPrimarySourceCapture:
    operator_id: str
    security_id: str
    as_of_cutoff: datetime
    capture_id: str
    capture_revision: int
    plan_id: str
    plan_revision: int
    plan_content_hash: str
    question_type: str
    question_type_version: str
    workflow_config_version: str
    thesis_contract_id: str
    eligibility_policy_version: str
    package_sha256: str
    capture_content_hash: str
    byte_length: int
    assembled_at: datetime
    accepted_at: datetime
    loader_version: str
    provenance_mode: str


@dataclass(frozen=True, slots=True)
class PrimarySourceRunArtifactBinding:
    operator_id: str
    research_run_id: str
    security_id: str
    as_of_cutoff: datetime
    question_type: str
    question_type_version: str
    workflow_config_version: str
    thesis_contract_id: str
    capture_id: str
    capture_revision: int
    package_sha256: str
    capture_content_hash: str
    plan_id: str
    plan_revision: int
    plan_content_hash: str
    bound_at: datetime


class FilePrimarySourceCaptureRepository:
    """Private restart-safe local storage for accepted capture archives."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        if self._root.is_symlink():
            raise PrimarySourceStorageError(
                "capture storage root must not be a symlink"
            )
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._root, 0o700)

    def save_capture(
        self,
        capture: PrimarySourceCapture,
        raw_archive: bytes,
    ) -> PersistedPrimarySourceCapture:
        metadata = _metadata_from_capture(capture, raw_archive)
        target = self._capture_directory(
            metadata.operator_id,
            metadata.capture_id,
            metadata.capture_revision,
        )
        existing = self.get_capture(
            metadata.operator_id,
            metadata.capture_id,
            metadata.capture_revision,
        )
        if existing is not None:
            self._require_exact(existing, metadata)
            if (
                self.read_archive(
                    metadata.operator_id,
                    metadata.capture_id,
                    metadata.capture_revision,
                )
                != raw_archive
            ):
                raise PrimarySourceStorageError("conflicting immutable capture archive")
            return existing

        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(target.parent, 0o700)
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{target.name}.",
                dir=target.parent,
            )
        )
        try:
            os.chmod(temporary, 0o700)
            _write_private_file(
                temporary / "capture.zip",
                raw_archive,
            )
            _write_private_file(
                temporary / "metadata.json",
                _canonical_metadata(metadata),
            )
            try:
                os.rename(temporary, target)
            except OSError:
                if not target.is_dir():
                    raise
                persisted = self.get_capture(
                    metadata.operator_id,
                    metadata.capture_id,
                    metadata.capture_revision,
                )
                if persisted is None:
                    raise
                self._require_exact(persisted, metadata)
                if (
                    self.read_archive(
                        metadata.operator_id,
                        metadata.capture_id,
                        metadata.capture_revision,
                    )
                    != raw_archive
                ):
                    raise PrimarySourceStorageError(
                        "conflicting immutable capture archive"
                    )
                return persisted
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return metadata

    def get_capture(
        self,
        operator_id: str,
        capture_id: str,
        revision: int,
    ) -> PersistedPrimarySourceCapture | None:
        target = self._capture_directory(
            operator_id,
            capture_id,
            revision,
        )
        if not target.exists():
            return None
        if not target.is_dir() or target.is_symlink():
            raise PrimarySourceStorageError("capture storage path is invalid")
        metadata_path = target / "metadata.json"
        if not metadata_path.is_file() or metadata_path.is_symlink():
            raise PrimarySourceStorageError("capture metadata is unavailable")
        try:
            payload = json.loads(metadata_path.read_text())
            metadata = _metadata_from_dict(payload)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise PrimarySourceStorageError("capture metadata is invalid") from error
        if (
            metadata.operator_id != _uuid_text(operator_id)
            or metadata.capture_id != _uuid_text(capture_id)
            or metadata.capture_revision != revision
        ):
            raise PrimarySourceStorageError("capture metadata identity mismatch")
        return metadata

    def read_archive(
        self,
        operator_id: str,
        capture_id: str,
        revision: int,
    ) -> bytes:
        metadata = self.get_capture(operator_id, capture_id, revision)
        if metadata is None:
            raise PrimarySourceStorageError("capture is unavailable")
        path = (
            self._capture_directory(
                operator_id,
                capture_id,
                revision,
            )
            / "capture.zip"
        )
        if not path.is_file() or path.is_symlink():
            raise PrimarySourceStorageError("capture archive is unavailable")
        archive = path.read_bytes()
        if (
            len(archive) != metadata.byte_length
            or hashlib.sha256(archive).hexdigest() != metadata.package_sha256
        ):
            raise PrimarySourceStorageError("capture archive integrity mismatch")
        return archive

    def load_capture(
        self,
        request: PrimarySourceRequest,
        capture_id: str,
        revision: int,
        *,
        trusted_issuer_hosts: tuple[str, ...],
    ) -> PrimarySourceCapture:
        metadata = self.get_capture(
            request.operator_id,
            capture_id,
            revision,
        )
        if metadata is None:
            raise PrimarySourceStorageError("capture is unavailable")
        if (
            metadata.security_id != request.security_id
            or metadata.as_of_cutoff != request.as_of_cutoff
        ):
            raise PrimarySourceStorageError("capture request identity mismatch")
        archive = self.read_archive(
            request.operator_id,
            capture_id,
            revision,
        )
        try:
            capture = load_primary_source_capture(
                archive,
                request=request,
                trusted_issuer_hosts=trusted_issuer_hosts,
                accepted_at=lambda: metadata.accepted_at,
            )
        except PrimarySourceCaptureError as error:
            raise PrimarySourceStorageError(
                "persisted capture failed revalidation"
            ) from error
        self._require_exact(
            metadata,
            _metadata_from_capture(capture, archive),
        )
        return capture

    def bind_to_run(
        self,
        persisted: PersistedPrimarySourceCapture,
        research_run: ResearchRun,
        *,
        bound_at: datetime,
    ) -> PrimarySourceRunArtifactBinding:
        stored = self.get_capture(
            persisted.operator_id,
            persisted.capture_id,
            persisted.capture_revision,
        )
        if stored is None or stored != persisted:
            raise PrimarySourceStorageError(
                "capture binding requires persisted artifact"
            )
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
        capture_identity = (
            persisted.operator_id,
            persisted.security_id,
            persisted.as_of_cutoff,
            persisted.question_type,
            persisted.question_type_version,
            persisted.workflow_config_version,
            persisted.thesis_contract_id,
            persisted.eligibility_policy_version,
        )
        if run_identity != capture_identity:
            raise PrimarySourceStorageError(
                "Research Run does not match persisted capture"
            )
        canonical_bound_at = _aware_timestamp(bound_at)
        if canonical_bound_at < persisted.accepted_at:
            raise PrimarySourceStorageError("capture binding predates acceptance")
        binding = PrimarySourceRunArtifactBinding(
            operator_id=persisted.operator_id,
            research_run_id=_uuid_text(research_run.id),
            security_id=persisted.security_id,
            as_of_cutoff=persisted.as_of_cutoff,
            question_type=persisted.question_type,
            question_type_version=persisted.question_type_version,
            workflow_config_version=persisted.workflow_config_version,
            thesis_contract_id=persisted.thesis_contract_id,
            capture_id=persisted.capture_id,
            capture_revision=persisted.capture_revision,
            package_sha256=persisted.package_sha256,
            capture_content_hash=persisted.capture_content_hash,
            plan_id=persisted.plan_id,
            plan_revision=persisted.plan_revision,
            plan_content_hash=persisted.plan_content_hash,
            bound_at=canonical_bound_at,
        )
        path = self._binding_path(
            binding.operator_id,
            binding.research_run_id,
        )
        existing = self.get_for_run(
            binding.operator_id,
            binding.research_run_id,
        )
        if existing is not None:
            if existing != binding:
                raise PrimarySourceStorageError(
                    "Research Run already has another capture"
                )
            return existing
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        _write_immutable_file(path, _canonical_binding(binding))
        restored = self.get_for_run(
            binding.operator_id,
            binding.research_run_id,
        )
        if restored != binding:
            raise PrimarySourceStorageError("persisted capture binding mismatch")
        return binding

    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> PrimarySourceRunArtifactBinding | None:
        path = self._binding_path(operator_id, research_run_id)
        if not path.exists():
            return None
        if not path.is_file() or path.is_symlink():
            raise PrimarySourceStorageError("capture binding path is invalid")
        try:
            binding = _binding_from_dict(json.loads(path.read_text()))
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise PrimarySourceStorageError("capture binding is invalid") from error
        if binding.operator_id != _uuid_text(
            operator_id
        ) or binding.research_run_id != _uuid_text(research_run_id):
            raise PrimarySourceStorageError("capture binding identity mismatch")
        return binding

    def _capture_directory(
        self,
        operator_id: str,
        capture_id: str,
        revision: int,
    ) -> Path:
        if type(revision) is not int or revision < 1:
            raise PrimarySourceStorageError("capture revision is invalid")
        return (
            self._root
            / _uuid_text(operator_id)
            / _uuid_text(capture_id)
            / str(revision)
        )

    def _binding_path(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> Path:
        return (
            self._root
            / _uuid_text(operator_id)
            / "run-bindings"
            / f"{_uuid_text(research_run_id)}.json"
        )

    @staticmethod
    def _require_exact(
        existing: PersistedPrimarySourceCapture,
        requested: PersistedPrimarySourceCapture,
    ) -> None:
        if existing != requested:
            raise PrimarySourceStorageError("conflicting immutable capture revision")


def _metadata_from_capture(
    capture: PrimarySourceCapture,
    raw_archive: bytes,
) -> PersistedPrimarySourceCapture:
    package_sha256 = hashlib.sha256(raw_archive).hexdigest()
    receipt = capture.receipt
    plan = capture.plan
    if (
        package_sha256 != receipt.package_sha256
        or receipt.capture_id != capture.capture_id
        or receipt.capture_revision != capture.revision
        or receipt.capture_content_hash != capture.content_hash
        or receipt.authenticated_operator_id != plan.operator_id
        or receipt.provenance_mode != capture.provenance_mode
    ):
        raise PrimarySourceStorageError("capture persistence identity mismatch")
    return PersistedPrimarySourceCapture(
        operator_id=_uuid_text(plan.operator_id),
        security_id=_uuid_text(plan.loaded.security_id),
        as_of_cutoff=plan.as_of_cutoff.astimezone(UTC),
        capture_id=_uuid_text(capture.capture_id),
        capture_revision=capture.revision,
        plan_id=_uuid_text(plan.loaded.plan_id),
        plan_revision=plan.loaded.revision,
        plan_content_hash=plan.content_hash,
        question_type=plan.loaded.question_type,
        question_type_version=plan.loaded.question_type_version,
        workflow_config_version=plan.loaded.workflow_config_version,
        thesis_contract_id=plan.loaded.thesis_contract_id,
        eligibility_policy_version=plan.loaded.eligibility_policy_version,
        package_sha256=package_sha256,
        capture_content_hash=capture.content_hash,
        byte_length=len(raw_archive),
        assembled_at=capture.assembled_at.astimezone(UTC),
        accepted_at=receipt.accepted_at.astimezone(UTC),
        loader_version=receipt.loader_version,
        provenance_mode=receipt.provenance_mode,
    )


def _canonical_metadata(
    metadata: PersistedPrimarySourceCapture,
) -> bytes:
    payload = {
        "contract_version": _METADATA_VERSION,
        **{
            key: (value.isoformat() if isinstance(value, datetime) else value)
            for key, value in asdict(metadata).items()
        },
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _metadata_from_dict(
    payload: object,
) -> PersistedPrimarySourceCapture:
    if not isinstance(payload, dict):
        raise ValueError("metadata must be an object")
    expected = {
        "contract_version",
        *PersistedPrimarySourceCapture.__dataclass_fields__,
    }
    if set(payload) != expected:
        raise ValueError("metadata fields are invalid")
    if payload["contract_version"] != _METADATA_VERSION:
        raise ValueError("metadata version is unsupported")
    metadata = PersistedPrimarySourceCapture(
        operator_id=_uuid_text(payload["operator_id"]),
        security_id=_uuid_text(payload["security_id"]),
        as_of_cutoff=_timestamp(payload["as_of_cutoff"]),
        capture_id=_uuid_text(payload["capture_id"]),
        capture_revision=int(payload["capture_revision"]),
        plan_id=_uuid_text(payload["plan_id"]),
        plan_revision=int(payload["plan_revision"]),
        plan_content_hash=str(payload["plan_content_hash"]),
        question_type=str(payload["question_type"]),
        question_type_version=str(payload["question_type_version"]),
        workflow_config_version=str(payload["workflow_config_version"]),
        thesis_contract_id=str(payload["thesis_contract_id"]),
        eligibility_policy_version=str(payload["eligibility_policy_version"]),
        package_sha256=str(payload["package_sha256"]),
        capture_content_hash=str(payload["capture_content_hash"]),
        byte_length=int(payload["byte_length"]),
        assembled_at=_timestamp(payload["assembled_at"]),
        accepted_at=_timestamp(payload["accepted_at"]),
        loader_version=str(payload["loader_version"]),
        provenance_mode=str(payload["provenance_mode"]),
    )
    if (
        metadata.capture_revision < 1
        or metadata.plan_revision < 1
        or metadata.byte_length < 1
        or _SHA256.fullmatch(metadata.plan_content_hash) is None
        or _SHA256.fullmatch(metadata.package_sha256) is None
        or _SHA256.fullmatch(metadata.capture_content_hash) is None
        or not metadata.question_type
        or not metadata.question_type_version
        or not metadata.workflow_config_version
        or not metadata.thesis_contract_id
        or not metadata.eligibility_policy_version
        or not metadata.loader_version
        or metadata.provenance_mode != "operator_supplied_unverified"
    ):
        raise ValueError("metadata values are invalid")
    return metadata


def _canonical_binding(
    binding: PrimarySourceRunArtifactBinding,
) -> bytes:
    payload = {
        "contract_version": "primary_source_run_artifact_binding.v1",
        **{
            key: (value.isoformat() if isinstance(value, datetime) else value)
            for key, value in asdict(binding).items()
        },
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _binding_from_dict(
    payload: object,
) -> PrimarySourceRunArtifactBinding:
    if not isinstance(payload, dict):
        raise ValueError("binding must be an object")
    expected = {
        "contract_version",
        *PrimarySourceRunArtifactBinding.__dataclass_fields__,
    }
    if set(payload) != expected or payload["contract_version"] != (
        "primary_source_run_artifact_binding.v1"
    ):
        raise ValueError("binding fields are invalid")
    binding = PrimarySourceRunArtifactBinding(
        operator_id=_uuid_text(payload["operator_id"]),
        research_run_id=_uuid_text(payload["research_run_id"]),
        security_id=_uuid_text(payload["security_id"]),
        as_of_cutoff=_timestamp(payload["as_of_cutoff"]),
        question_type=str(payload["question_type"]),
        question_type_version=str(payload["question_type_version"]),
        workflow_config_version=str(payload["workflow_config_version"]),
        thesis_contract_id=str(payload["thesis_contract_id"]),
        capture_id=_uuid_text(payload["capture_id"]),
        capture_revision=int(payload["capture_revision"]),
        package_sha256=str(payload["package_sha256"]),
        capture_content_hash=str(payload["capture_content_hash"]),
        plan_id=_uuid_text(payload["plan_id"]),
        plan_revision=int(payload["plan_revision"]),
        plan_content_hash=str(payload["plan_content_hash"]),
        bound_at=_timestamp(payload["bound_at"]),
    )
    if (
        binding.capture_revision < 1
        or binding.plan_revision < 1
        or _SHA256.fullmatch(binding.package_sha256) is None
        or _SHA256.fullmatch(binding.capture_content_hash) is None
        or _SHA256.fullmatch(binding.plan_content_hash) is None
        or not binding.question_type
        or not binding.question_type_version
        or not binding.workflow_config_version
        or not binding.thesis_contract_id
    ):
        raise ValueError("binding values are invalid")
    return binding


def _write_private_file(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "wb") as handle:
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            os.fchmod(handle.fileno(), 0o600)


def _write_immutable_file(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing = path.read_bytes()
            if existing != content:
                raise PrimarySourceStorageError("conflicting immutable capture binding")
    finally:
        temporary.unlink(missing_ok=True)


def _timestamp(value: object) -> datetime:
    timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return timestamp.astimezone(UTC)


def _aware_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PrimarySourceStorageError("storage timestamp must include timezone")
    return value.astimezone(UTC)


def _uuid_text(value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as error:
        raise PrimarySourceStorageError("storage identity must be a UUID") from error


__all__ = [
    "FilePrimarySourceCaptureRepository",
    "PersistedPrimarySourceCapture",
    "PrimarySourceRunArtifactBinding",
    "PrimarySourceStorageError",
]
