"""Durable local storage for imported datasets and computed results.

Two stores, one directory tree, one rule each.

The **dataset store** holds the last validated document an operator imported
for one security, so the workspace survives a worker restart without asking for
the file again. It holds the document, not the receipt object: rebuilding the
receipt through the same intake path on every load means a stored file can
never grant a dataset guarantees the intake rules would refuse today.

The **result store** is content-addressed by run key. A run key is a function of
the dataset hash and the declared assumptions, so an identical request after a
restart reloads the identical record rather than recomputing a number that
might drift.

Every path is derived from canonical UUID text alone, never from caller-supplied
path fragments, and every directory on the way down is refused if it is a
symlink. Writes are atomic and owner-only. A record that fails to load cleanly
reads as missing, so a corrupted file degrades to "import again" rather than to
a plausible-looking number nobody can reproduce.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Mapping
from uuid import UUID

from workers.quant_workspace.intake import QuantWorkspaceError

DATASET_RECORD_CONTRACT_VERSION = "quant_local_dataset_record.v1"

#: A stored record is small. This cap refuses anything that grew into something
#: else before it is parsed.
MAX_RECORD_BYTES = 16 * 1024 * 1024
_SHA256_DIGITS = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class StoredDataset:
    """One reloaded dataset document and the receipt hash it produced."""

    document: Mapping[str, object]
    dataset_sha256: str


def _identity(value: object) -> str:
    """Canonical UUID text, or a refusal.

    This is the only source of a path segment in this module. A value that is
    not canonical UUID text never becomes a directory name, so traversal is not
    something the path builder has to defend against later.
    """

    if not isinstance(value, str):
        raise QuantWorkspaceError(
            "workspace_identity_invalid", "identity must be canonical UUID text"
        )
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise QuantWorkspaceError(
            "workspace_identity_invalid", "identity must be canonical UUID text"
        ) from error
    if str(parsed) != value:
        raise QuantWorkspaceError(
            "workspace_identity_invalid", "identity must be canonical UUID text"
        )
    return value


def _digest(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or not set(value) <= _SHA256_DIGITS
    ):
        raise QuantWorkspaceError(
            "workspace_identity_invalid",
            "content hash must be a lowercase SHA-256 digest",
        )
    return value


class FileQuantWorkspaceStore:
    """Local, owner-only persistence for the Quant workspace."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _leaf(self, *segments: str, create: bool) -> Path:
        """Walk down to one leaf path, refusing a symlink at any level.

        The check runs on every level rather than on the leaf alone: a symlink
        planted at the operator level redirects everything beneath it, and a
        leaf-only check would never see it.
        """

        current = self._root
        if current.is_symlink():
            raise QuantWorkspaceError(
                "workspace_store_unsafe", "workspace root must not be a symlink"
            )
        for segment in segments[:-1]:
            current = current / segment
            if current.is_symlink():
                raise QuantWorkspaceError(
                    "workspace_store_unsafe",
                    "workspace directory must not be a symlink",
                )
        if create:
            try:
                current.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise QuantWorkspaceError(
                    "workspace_store_unsafe", "workspace directory is unusable"
                ) from error
        leaf = current / segments[-1]
        if leaf.is_symlink():
            raise QuantWorkspaceError(
                "workspace_store_unsafe", "workspace file must not be a symlink"
            )
        return leaf

    def _dataset_path(self, *, operator_id: str, security_id: str, create: bool) -> Path:
        return self._leaf(
            "datasets",
            _identity(operator_id),
            f"{_identity(security_id)}.json",
            create=create,
        )

    def _result_path(
        self, *, operator_id: str, security_id: str, run_key: str, create: bool
    ) -> Path:
        return self._leaf(
            "results",
            _identity(operator_id),
            _identity(security_id),
            f"{_digest(run_key)}.json",
            create=create,
        )

    def _latest_path(
        self, *, operator_id: str, security_id: str, create: bool
    ) -> Path:
        return self._leaf(
            "results",
            _identity(operator_id),
            _identity(security_id),
            "latest.json",
            create=create,
        )

    def _write(self, path: Path, record: Mapping[str, object]) -> None:
        """Atomic, owner-only replace through a same-directory temp file.

        Same directory so the final ``os.replace`` is a rename rather than a
        copy, and ``0600`` before any content is written so the record is never
        briefly world-readable.
        """

        body = json.dumps(record, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                dir=path.parent, delete=False, suffix=".tmp"
            ) as handle:
                temporary = Path(handle.name)
                os.chmod(handle.name, 0o600)
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
        except OSError as error:
            raise QuantWorkspaceError(
                "workspace_store_unsafe", "workspace record could not be written"
            ) from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _read(self, path: Path) -> Mapping[str, object] | None:
        try:
            if path.stat().st_size > MAX_RECORD_BYTES:
                return None
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(record, dict):
            return None
        return record

    def save_dataset(
        self,
        *,
        operator_id: str,
        security_id: str,
        document: Mapping[str, object],
        dataset_sha256: str,
    ) -> None:
        """Replace the active dataset for one security.

        One active dataset per security is deliberate. A workspace that kept
        several would have to answer which one a result was computed against,
        and the result record already answers that with a hash.
        """

        path = self._dataset_path(
            operator_id=operator_id, security_id=security_id, create=True
        )
        self._write(
            path,
            {
                "contract_version": DATASET_RECORD_CONTRACT_VERSION,
                "dataset_sha256": _digest(dataset_sha256),
                "document": dict(document),
                "security_id": security_id,
            },
        )

    def load_dataset(
        self, *, operator_id: str, security_id: str
    ) -> StoredDataset | None:
        try:
            path = self._dataset_path(
                operator_id=operator_id, security_id=security_id, create=False
            )
        except QuantWorkspaceError as error:
            # An unsafe location is never followed on a read either. It reads as
            # "no dataset", so the workspace asks for an import instead of
            # serving whatever the symlink points at.
            if error.code == "workspace_store_unsafe":
                return None
            raise
        record = self._read(path)
        if record is None:
            return None
        if (
            record.get("contract_version") != DATASET_RECORD_CONTRACT_VERSION
            or record.get("security_id") != security_id
            or not isinstance(record.get("document"), dict)
            or not isinstance(record.get("dataset_sha256"), str)
        ):
            return None
        try:
            digest = _digest(record["dataset_sha256"])
        except QuantWorkspaceError:
            return None
        return StoredDataset(
            document=record["document"],  # type: ignore[arg-type]
            dataset_sha256=digest,
        )

    def save_result(
        self,
        *,
        operator_id: str,
        security_id: str,
        run_key: str,
        record: Mapping[str, object],
    ) -> None:
        path = self._result_path(
            operator_id=operator_id,
            security_id=security_id,
            run_key=run_key,
            create=True,
        )
        self._write(path, dict(record))

    def save_latest_run_key(
        self, *, operator_id: str, security_id: str, run_key: str | None
    ) -> None:
        """Point at the run to show for this security, or at nothing.

        A pointer rather than a second copy of the record: two copies would
        eventually disagree, and the one on screen would be the one nobody
        could reproduce. Clearing it is a first-class operation, used when a
        newly imported dataset makes the previous result no longer comparable.
        """

        path = self._latest_path(
            operator_id=operator_id, security_id=security_id, create=True
        )
        if run_key is None:
            path.unlink(missing_ok=True)
            return
        self._write(path, {"run_key": _digest(run_key), "security_id": security_id})

    def load_latest_run_key(
        self, *, operator_id: str, security_id: str
    ) -> str | None:
        try:
            path = self._latest_path(
                operator_id=operator_id, security_id=security_id, create=False
            )
        except QuantWorkspaceError as error:
            if error.code == "workspace_store_unsafe":
                return None
            raise
        record = self._read(path)
        if record is None or record.get("security_id") != security_id:
            return None
        try:
            return _digest(record.get("run_key"))
        except QuantWorkspaceError:
            return None

    def load_result(
        self, *, operator_id: str, security_id: str, run_key: str
    ) -> Mapping[str, object] | None:
        try:
            path = self._result_path(
                operator_id=operator_id,
                security_id=security_id,
                run_key=run_key,
                create=False,
            )
        except QuantWorkspaceError as error:
            if error.code == "workspace_store_unsafe":
                return None
            raise
        record = self._read(path)
        if record is None or record.get("security_id") != security_id:
            return None
        return record
