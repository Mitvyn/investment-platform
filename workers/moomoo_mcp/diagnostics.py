"""Bounded, redacted desktop-local lifecycle diagnostics for Moomoo connections.

Replaces silently discarding worker stderr with a small, structured,
size-bounded log of *safe* lifecycle events: a timestamp, which subsystem
(`core_mcp` or `optional_stream`), a lifecycle stage, and one bounded reason
code. It never accepts or stores free-form provider exception text, tokens,
authorization codes, verifiers, callback URLs/queries, client IDs, account
IDs, holdings, raw schemas, or raw provider payloads -- callers pass only the
same bounded reason codes already used for status reporting.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime

MAX_DIAGNOSTIC_ENTRIES = 200
MAX_REASON_CODE_LENGTH = 128
MAX_STAGE_LENGTH = 64

_ALLOWED_SUBSYSTEMS = frozenset({"core_mcp", "optional_stream"})

# A conservative safe-character allowlist for stage/reason_code: lowercase
# identifiers only. Rejects anything that looks like it could carry a
# provider payload, URL, or free-form exception text.
_SAFE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def _is_safe_identifier(value: str, *, max_length: int) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= max_length
        and all(char in _SAFE_CHARS for char in value)
    )


@dataclass(frozen=True, slots=True)
class MoomooDiagnosticEntry:
    timestamp: datetime
    subsystem: str
    stage: str
    reason_code: str

    def as_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "subsystem": self.subsystem,
            "stage": self.stage,
            "reason_code": self.reason_code,
        }


class MoomooDiagnosticsLog:
    """Fixed-capacity, thread-safe-by-caller-discipline ring buffer.

    Callers (`MoomooConnectionService`, which already holds its own lock
    around the state transitions this records) are responsible for
    serializing writes; this class only enforces the bound and the safe-
    value contract.
    """

    def __init__(
        self,
        *,
        max_entries: int = MAX_DIAGNOSTIC_ENTRIES,
        clock=None,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("Moomoo diagnostics log capacity must be positive")
        self._entries: deque[MoomooDiagnosticEntry] = deque(maxlen=max_entries)
        self._clock = clock or (lambda: datetime.now())

    def record(self, *, subsystem: str, stage: str, reason_code: str) -> None:
        if subsystem not in _ALLOWED_SUBSYSTEMS:
            raise ValueError("Unknown Moomoo diagnostics subsystem")
        if not _is_safe_identifier(stage, max_length=MAX_STAGE_LENGTH):
            raise ValueError("Moomoo diagnostics stage must be a bounded safe identifier")
        if not _is_safe_identifier(reason_code, max_length=MAX_REASON_CODE_LENGTH):
            raise ValueError(
                "Moomoo diagnostics reason code must be a bounded safe identifier"
            )
        self._entries.append(
            MoomooDiagnosticEntry(
                timestamp=self._clock(),
                subsystem=subsystem,
                stage=stage,
                reason_code=reason_code,
            )
        )

    def recent(self, *, limit: int | None = None) -> tuple[MoomooDiagnosticEntry, ...]:
        entries = tuple(self._entries)
        if limit is None:
            return entries
        if limit <= 0:
            return ()
        return entries[-limit:]


__all__ = [
    "MAX_DIAGNOSTIC_ENTRIES",
    "MoomooDiagnosticEntry",
    "MoomooDiagnosticsLog",
]
