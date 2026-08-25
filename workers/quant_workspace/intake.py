"""Local dataset intake for the Quant workspace.

An operator holds a daily OHLCV history in a local file. This module is the one
place that file becomes a validated ``PointInTimeDataset``. It accepts exactly
one explicit, provider-neutral document contract and refuses everything else,
including a document that merely looks close enough.

Two properties matter more than convenience here.

**Nothing is inferred.** The canonical ``security_id``, the currency, the
as-of cutoff, the source identity, the source revision, and the source content
hash are all declared in the document and checked against the request. A
missing declaration is a rejection, never a default, because a dataset whose
provenance nobody stated cannot be audited later.

**Failures are coded, not narrated.** Every rejection raises
:class:`QuantWorkspaceError` carrying a code from a fixed vocabulary. The
underlying message stays local for the operator's own logs; only the code
crosses the process boundary, so no fragment of a source document can be
reflected into the browser or into documentation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence
from uuid import UUID

from investment_research_os.quant import PointInTimeDataset, QuantContractError
from investment_research_os.quant_sources import (
    SourceSnapshot,
    acquire_point_in_time_dataset,
    payload_sha256,
)

LOCAL_DATASET_CONTRACT_VERSION = "quant_local_dataset.v1"

#: A daily single-security history is small. This cap is generous for decades
#: of sessions and still refuses a file large enough to be something else
#: entirely before any of it is parsed.
MAX_DATASET_FILE_BYTES = 8 * 1024 * 1024
MAX_BAR_ROWS = 20_000
MAX_SPLIT_ROWS = 500

_DOCUMENT_FIELDS = frozenset(
    {
        "as_of_cutoff",
        "bars",
        "contract_version",
        "corporate_actions",
        "currency",
        "security_id",
        "source_content_sha256",
        "source_id",
        "source_revision",
    }
)
_BAR_FIELDS = frozenset({"session", "open", "high", "low", "close", "volume"})
_SPLIT_FIELDS = frozenset({"effective_session", "new_shares", "old_shares"})
_SHA256_DIGITS = frozenset("0123456789abcdef")

#: Every rejection code this module can raise. The dashboard maps each one to
#: plain language; nothing outside this set ever reaches a caller.
DATASET_ERROR_CODES = frozenset(
    {
        "dataset_contract_invalid",
        "dataset_currency_invalid",
        "dataset_cutoff_invalid",
        "dataset_file_unreadable",
        "dataset_future_data",
        "dataset_hash_mismatch",
        "dataset_path_invalid",
        "dataset_rows_invalid",
        "dataset_security_mismatch",
        "dataset_sessions_invalid",
        "dataset_split_uncovered",
        "dataset_too_large",
    }
)


class QuantWorkspaceError(ValueError):
    """A coded Quant workspace failure.

    ``code`` is the only part designed to leave this process. The message is
    for local diagnosis and may name a field, so callers that cross a trust
    boundary must send the code alone.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class LocalDatasetImportRequest:
    """One operator request to import one local file for one security."""

    operator_id: str
    security_id: str
    dataset_path: Path


def _canonical_uuid(value: object, *, code: str) -> str:
    if not isinstance(value, str):
        raise QuantWorkspaceError(code, "identity must be canonical UUID text")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise QuantWorkspaceError(
            code, "identity must be canonical UUID text"
        ) from error
    if str(parsed) != value:
        raise QuantWorkspaceError(code, "identity must be canonical UUID text")
    return value


def canonical_identity(value: object) -> str:
    """Canonical UUID text for an operator or security, or a refusal.

    Exposed because callers that read a document directly still owe the same
    identity check the full import performs.
    """

    return _canonical_uuid(value, code="workspace_identity_invalid")


def read_local_dataset_document(path: object) -> Mapping[str, object]:
    """Read and shape-check one local dataset file.

    Path safety comes before parsing, and size before decoding: a symlinked
    file or a symlinked parent directory is refused outright rather than
    followed, and an oversized file is rejected without being read into memory.
    """

    if not isinstance(path, Path) or not path.is_absolute():
        raise QuantWorkspaceError(
            "dataset_path_invalid", "dataset path must be absolute"
        )
    if path.is_symlink() or path.parent.is_symlink():
        raise QuantWorkspaceError(
            "dataset_path_invalid",
            "dataset path must not be a symlink or sit under one",
        )
    try:
        stat = path.stat()
    except OSError as error:
        raise QuantWorkspaceError(
            "dataset_file_unreadable", "dataset file cannot be read"
        ) from error
    if not path.is_file():
        raise QuantWorkspaceError(
            "dataset_file_unreadable", "dataset path is not a regular file"
        )
    if stat.st_size > MAX_DATASET_FILE_BYTES:
        raise QuantWorkspaceError(
            "dataset_too_large", "dataset file exceeds the supported size"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise QuantWorkspaceError(
            "dataset_contract_invalid", "dataset file is not valid JSON"
        ) from error
    if not isinstance(document, dict):
        raise QuantWorkspaceError(
            "dataset_contract_invalid", "dataset document must be an object"
        )
    if set(document) != _DOCUMENT_FIELDS:
        raise QuantWorkspaceError(
            "dataset_contract_invalid",
            "dataset document fields do not match the supported contract",
        )
    if document["contract_version"] != LOCAL_DATASET_CONTRACT_VERSION:
        raise QuantWorkspaceError(
            "dataset_contract_invalid",
            "dataset contract version is not supported",
        )
    return document


def _rows(value: object, *, maximum: int, required: frozenset[str]) -> tuple[
    Mapping[str, object], ...
]:
    if not isinstance(value, list) or len(value) > maximum:
        raise QuantWorkspaceError(
            "dataset_contract_invalid", "dataset rows are not a bounded list"
        )
    rows: list[Mapping[str, object]] = []
    for row in value:
        if not isinstance(row, dict) or not required <= set(row):
            raise QuantWorkspaceError(
                "dataset_rows_invalid", "dataset row is missing required fields"
            )
        rows.append(row)
    return tuple(rows)


def _session(value: object, *, code: str) -> date:
    if not isinstance(value, str):
        raise QuantWorkspaceError(code, "session must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise QuantWorkspaceError(code, "session is not an ISO date") from error


def _check_sessions(rows: Sequence[Mapping[str, object]]) -> tuple[date, ...]:
    """Strictly increasing sessions. Duplicates and reordering both fail here.

    Sorting would be the friendlier move and the wrong one: a source that sent
    a duplicate or an out-of-order session sent something the operator should
    see, not something this module should quietly repair.
    """

    sessions = tuple(
        _session(row["session"], code="dataset_sessions_invalid") for row in rows
    )
    for earlier, later in zip(sessions, sessions[1:]):
        if later <= earlier:
            raise QuantWorkspaceError(
                "dataset_sessions_invalid",
                "sessions must be strictly increasing with no duplicates",
            )
    return sessions


def build_dataset(
    document: Mapping[str, object], *, security_id: str
) -> PointInTimeDataset:
    """Turn one checked document into one validated point-in-time receipt.

    The order is deliberate: identity, then declarations, then dates, then
    payload integrity, and only then the Quant acquisition boundary. Each stage
    can name why it refused, and the last stage never sees a document whose
    earlier claims were untrue.
    """

    declared_security = _canonical_uuid(
        document["security_id"], code="dataset_security_mismatch"
    )
    if declared_security != security_id:
        raise QuantWorkspaceError(
            "dataset_security_mismatch",
            "dataset declares a different canonical security",
        )

    currency = document["currency"]
    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isupper()
        or not currency.isalpha()
    ):
        raise QuantWorkspaceError(
            "dataset_currency_invalid",
            "currency must be an upper-case ISO 4217 code",
        )

    cutoff = _session(document["as_of_cutoff"], code="dataset_cutoff_invalid")

    for field in ("source_id", "source_revision"):
        value = document[field]
        if not isinstance(value, str) or not value.strip():
            raise QuantWorkspaceError(
                "dataset_contract_invalid", f"{field} must be a non-empty string"
            )
    declared_hash = document["source_content_sha256"]
    if (
        not isinstance(declared_hash, str)
        or len(declared_hash) != 64
        or not set(declared_hash) <= _SHA256_DIGITS
    ):
        raise QuantWorkspaceError(
            "dataset_hash_mismatch",
            "source_content_sha256 must be a lowercase SHA-256 digest",
        )

    bars = _rows(document["bars"], maximum=MAX_BAR_ROWS, required=_BAR_FIELDS)
    splits = _rows(
        document["corporate_actions"], maximum=MAX_SPLIT_ROWS, required=_SPLIT_FIELDS
    )

    sessions = _check_sessions(bars)
    if any(session > cutoff for session in sessions):
        raise QuantWorkspaceError(
            "dataset_future_data",
            "a session falls after the declared as-of cutoff",
        )
    # The engine transitions into every bar except the first, so a split dated
    # on the first bar or on a session the file does not contain could never be
    # applied. Both are the operator's to fix, and both are named here rather
    # than surfacing much later as an engine contract error.
    covered = frozenset(sessions[1:])
    for split in splits:
        effective = _session(
            split["effective_session"], code="dataset_sessions_invalid"
        )
        if effective > cutoff:
            raise QuantWorkspaceError(
                "dataset_future_data",
                "a corporate action falls after the declared as-of cutoff",
            )
        if effective not in covered:
            raise QuantWorkspaceError(
                "dataset_split_uncovered",
                "a corporate action is not on a covered transition session",
            )

    try:
        recomputed = payload_sha256(bar_rows=bars, split_rows=splits)
    except QuantContractError as error:
        # A value the canonical hash cannot represent, a float price above all
        # others. It fails here before the integrity check rather than being
        # reported as a hash mismatch, which would name the wrong cause.
        raise QuantWorkspaceError(
            "dataset_rows_invalid", "dataset rows contain unhashable values"
        ) from error
    if recomputed != declared_hash:
        raise QuantWorkspaceError(
            "dataset_hash_mismatch",
            "payload does not match its declared source content hash",
        )

    try:
        snapshot = SourceSnapshot(
            source_id=str(document["source_id"]),
            source_revision=str(document["source_revision"]),
            content_sha256=declared_hash,
            bar_rows=bars,
            split_rows=splits,
        )
        return acquire_point_in_time_dataset(
            security_id=security_id,
            as_of_cutoff=cutoff,
            currency=currency,
            snapshot=snapshot,
        )
    except QuantContractError as error:
        # The Quant contracts own the remaining rules: price quanta, float
        # rejection, high/low coherence, minimum series length, and unknown
        # columns. Restating them here would create a second copy that drifts,
        # so their refusal is translated into one code instead.
        raise QuantWorkspaceError(
            "dataset_rows_invalid", "dataset rows do not satisfy the bar contract"
        ) from error


def import_local_dataset(
    request: LocalDatasetImportRequest,
) -> PointInTimeDataset:
    """Read, validate, and freeze one local dataset file for one security."""

    _canonical_uuid(request.operator_id, code="dataset_path_invalid")
    security_id = _canonical_uuid(request.security_id, code="dataset_security_mismatch")
    document = read_local_dataset_document(request.dataset_path)
    return build_dataset(document, security_id=security_id)
