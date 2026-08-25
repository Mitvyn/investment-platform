"""Bounded, redacted desktop-local lifecycle diagnostics for Moomoo connections.

Replaces silently discarding worker stderr with a small, structured,
size-bounded log of *safe* lifecycle events: a timestamp, which subsystem
(`core_mcp` or `optional_stream`), a lifecycle stage, and one bounded reason
code. Malformed MCP results may also carry a fixed-vocabulary shape summary:
only categories and bounded counts, never provider values, keys, or payloads.
It never accepts or stores free-form provider exception text, tokens,
authorization codes, verifiers, callback URLs/queries, client IDs, account
IDs, holdings, raw schemas, or raw provider payloads.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile

MAX_DIAGNOSTIC_ENTRIES = 200
MAX_REASON_CODE_LENGTH = 128
MAX_STAGE_LENGTH = 64
MAX_CONTENT_ITEMS = 8
DIAGNOSTICS_FILE_CONTRACT_VERSION = "moomoo_diagnostics_local.v1"

_ALLOWED_SUBSYSTEMS = frozenset({"core_mcp", "optional_stream"})

# A conservative safe-character allowlist for stage/reason_code: lowercase
# identifiers only. Rejects anything that looks like it could carry a
# provider payload, URL, or free-form exception text.
_SAFE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")
_STRUCTURED_KINDS = frozenset({"missing", "null", "object", "array", "scalar"})
_STRUCTURED_SHAPES = frozenset(
    {
        "missing",
        "empty",
        "quote_wrapper",
        "history_wrapper",
        "accounts_wrapper",
        "positions_wrapper",
        "s_d_envelope",
        "ret_envelope",
        "object",
        "array",
        "scalar",
    }
)
_CONTENT_KINDS = frozenset({"missing", "null", "object", "array", "scalar"})
_CONTENT_TYPES = frozenset({"text", "image", "audio", "resource", "resource_link", "other"})
_TEXT_JSON_KINDS = frozenset({"missing", "null", "object", "array", "scalar", "invalid"})


def _is_safe_identifier(value: str, *, max_length: int) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= max_length
        and all(char in _SAFE_CHARS for char in value)
    )


@dataclass(frozen=True, slots=True)
class MoomooResultShape:
    """Payload-free, fixed-vocabulary summary of one MCP result envelope."""

    structured_kind: str
    structured_shape: str
    content_kind: str
    content_count: int
    content_types: tuple[str, ...]
    text_json_kind: str

    def as_dict(self) -> dict[str, object]:
        return {
            "structured_kind": self.structured_kind,
            "structured_shape": self.structured_shape,
            "content_kind": self.content_kind,
            "content_count": self.content_count,
            "content_types": list(self.content_types),
            "text_json_kind": self.text_json_kind,
        }


def _load_result_shape(value: object) -> MoomooResultShape | None:
    if not isinstance(value, Mapping):
        return None
    expected_keys = {
        "structured_kind",
        "structured_shape",
        "content_kind",
        "content_count",
        "content_types",
        "text_json_kind",
    }
    if set(value) != expected_keys:
        return None
    structured_kind = value.get("structured_kind")
    structured_shape = value.get("structured_shape")
    content_kind = value.get("content_kind")
    content_count = value.get("content_count")
    content_types = value.get("content_types")
    text_json_kind = value.get("text_json_kind")
    if (
        not isinstance(structured_kind, str)
        or not isinstance(structured_shape, str)
        or not isinstance(content_kind, str)
        or structured_kind not in _STRUCTURED_KINDS
        or structured_shape not in _STRUCTURED_SHAPES
        or content_kind not in _CONTENT_KINDS
        or not isinstance(content_count, int)
        or isinstance(content_count, bool)
        or not 0 <= content_count <= MAX_CONTENT_ITEMS
        or not isinstance(content_types, list)
        or len(content_types) != content_count
        or any(
            not isinstance(item, str) or item not in _CONTENT_TYPES
            for item in content_types
        )
        or not isinstance(text_json_kind, str)
        or text_json_kind not in _TEXT_JSON_KINDS
    ):
        return None
    return MoomooResultShape(
        structured_kind=structured_kind,
        structured_shape=structured_shape,
        content_kind=content_kind,
        content_count=content_count,
        content_types=tuple(content_types),
        text_json_kind=text_json_kind,
    )


def _load_entry(value: object) -> MoomooDiagnosticEntry | None:
    if not isinstance(value, Mapping):
        return None
    expected_keys = {"timestamp", "subsystem", "stage", "reason_code"}
    if "shape" in value:
        expected_keys.add("shape")
    if set(value) != expected_keys:
        return None
    timestamp = value.get("timestamp")
    subsystem = value.get("subsystem")
    stage = value.get("stage")
    reason_code = value.get("reason_code")
    if (
        not isinstance(timestamp, str)
        or not isinstance(subsystem, str)
        or subsystem not in _ALLOWED_SUBSYSTEMS
        or not isinstance(stage, str)
        or not _is_safe_identifier(stage, max_length=MAX_STAGE_LENGTH)
        or not isinstance(reason_code, str)
        or not _is_safe_identifier(reason_code, max_length=MAX_REASON_CODE_LENGTH)
    ):
        return None
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    shape = _load_result_shape(value.get("shape")) if "shape" in value else None
    if "shape" in value and shape is None:
        return None
    return MoomooDiagnosticEntry(
        timestamp=parsed_timestamp,
        subsystem=subsystem,
        stage=stage,
        reason_code=reason_code,
        shape=shape,
    )


def _value_kind(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return "scalar"


def _structured_shape(value: object) -> str:
    if isinstance(value, Mapping):
        keys = set(value)
        if not keys:
            return "empty"
        if keys == {"quote_list"}:
            return "quote_wrapper"
        if keys == {"history_list"}:
            return "history_wrapper"
        if keys == {"accounts"}:
            return "accounts_wrapper"
        if keys == {"positions"}:
            return "positions_wrapper"
        if keys == {"s", "d"}:
            return "s_d_envelope"
        if keys == {"ret_code", "ret_msg", "data"}:
            return "ret_envelope"
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return "scalar"


def _content_item_type(value: object) -> str:
    if not isinstance(value, Mapping):
        return "other"
    value_type = value.get("type")
    if value_type in {"text", "image", "audio", "resource", "resource_link"}:
        return str(value_type)
    return "other"


def _text_json_kind(content: object) -> str:
    if not isinstance(content, (list, tuple)):
        return "missing"
    for item in content[:MAX_CONTENT_ITEMS]:
        if not isinstance(item, Mapping) or item.get("type") != "text":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            return "invalid"
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return "invalid"
        return _value_kind(parsed)
    return "missing"


def summarize_mcp_result_shape(result: Mapping[str, object]) -> MoomooResultShape:
    """Return bounded shape metadata without retaining provider payload data."""

    structured_present = "structuredContent" in result
    structured = result.get("structuredContent")
    structured_kind = _value_kind(structured) if structured_present else "missing"
    content_present = "content" in result
    content = result.get("content")
    if isinstance(content, (list, tuple)):
        content_kind = "array"
        content_count = min(len(content), MAX_CONTENT_ITEMS)
        content_types = tuple(_content_item_type(item) for item in content[:MAX_CONTENT_ITEMS])
    elif not content_present:
        content_kind = "missing"
        content_count = 0
        content_types = ()
    else:
        content_kind = _value_kind(content)
        content_count = 0
        content_types = ()
    return MoomooResultShape(
        structured_kind=structured_kind,
        structured_shape=(
            _structured_shape(structured) if structured_present else "missing"
        ),
        content_kind=content_kind,
        content_count=content_count,
        content_types=content_types,
        text_json_kind=_text_json_kind(content),
    )


@dataclass(frozen=True, slots=True)
class MoomooDiagnosticEntry:
    timestamp: datetime
    subsystem: str
    stage: str
    reason_code: str
    shape: MoomooResultShape | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "timestamp": self.timestamp.isoformat(),
            "subsystem": self.subsystem,
            "stage": self.stage,
            "reason_code": self.reason_code,
        }
        if self.shape is not None:
            result["shape"] = self.shape.as_dict()
        return result


class MoomooDiagnosticsLog:
    """Fixed-capacity, thread-safe-by-caller-discipline ring buffer.

    Callers (`MoomooConnectionService`, which already holds its own lock
    around the state transitions this records) are responsible for
    serializing writes; this class only enforces the bound and the safe-value
    contract.
    """

    def __init__(
        self,
        *,
        max_entries: int = MAX_DIAGNOSTIC_ENTRIES,
        clock=None,
        path: Path | None = None,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("Moomoo diagnostics log capacity must be positive")
        self._entries: deque[MoomooDiagnosticEntry] = deque(maxlen=max_entries)
        self._clock = clock or (lambda: datetime.now())
        self._path = path
        self._load()

    def _load(self) -> None:
        if self._path is None or self._path.is_symlink():
            return
        try:
            if self._path.stat().st_size > 256 * 1024:
                return
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, Mapping):
            return
        if payload.get("contract_version") != DIAGNOSTICS_FILE_CONTRACT_VERSION:
            return
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return
        loaded = tuple(_load_entry(entry) for entry in entries[:MAX_DIAGNOSTIC_ENTRIES])
        if any(entry is None for entry in loaded):
            return
        self._entries.extend(entry for entry in loaded if entry is not None)

    def _persist(self) -> None:
        if self._path is None:
            return
        if self._path.is_symlink() or self._path.parent.is_symlink():
            return
        temporary_path: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                os.chmod(temporary.name, 0o600)
                json.dump(
                    {
                        "contract_version": DIAGNOSTICS_FILE_CONTRACT_VERSION,
                        "entries": [entry.as_dict() for entry in self._entries],
                    },
                    temporary,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._path)
            temporary_path = None
        except OSError:
            pass
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    def record(
        self,
        *,
        subsystem: str,
        stage: str,
        reason_code: str,
        shape: MoomooResultShape | None = None,
    ) -> None:
        if subsystem not in _ALLOWED_SUBSYSTEMS:
            raise ValueError("Unknown Moomoo diagnostics subsystem")
        if not _is_safe_identifier(stage, max_length=MAX_STAGE_LENGTH):
            raise ValueError("Moomoo diagnostics stage must be a bounded safe identifier")
        if not _is_safe_identifier(reason_code, max_length=MAX_REASON_CODE_LENGTH):
            raise ValueError(
                "Moomoo diagnostics reason code must be a bounded safe identifier"
            )
        if shape is not None and not isinstance(shape, MoomooResultShape):
            raise ValueError("Moomoo diagnostics shape must be a typed result shape")
        self._entries.append(
            MoomooDiagnosticEntry(
                timestamp=self._clock(),
                subsystem=subsystem,
                stage=stage,
                reason_code=reason_code,
                shape=shape,
            )
        )
        self._persist()

    def recent(self, *, limit: int | None = None) -> tuple[MoomooDiagnosticEntry, ...]:
        entries = tuple(self._entries)
        if limit is None:
            return entries
        if limit <= 0:
            return ()
        return entries[-limit:]

    def clear(self) -> None:
        self._entries.clear()
        self._persist()


__all__ = [
    "MAX_DIAGNOSTIC_ENTRIES",
    "MoomooDiagnosticEntry",
    "MoomooDiagnosticsLog",
    "MoomooResultShape",
    "summarize_mcp_result_shape",
]
