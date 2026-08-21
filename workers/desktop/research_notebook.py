from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_NOTE_BODY_CHARS = 4_000
MAX_NOTES_RETURNED = 100


class TickerNotebookError(ValueError):
    """Raised when a notebook request fails validation."""


def _validate_security_id(security_id: str) -> str:
    if not isinstance(security_id, str) or not _UUID_PATTERN.fullmatch(security_id):
        raise TickerNotebookError("ticker notebook security_id is invalid")
    return security_id.lower()


def _validate_body(body: str) -> str:
    if not isinstance(body, str):
        raise TickerNotebookError("ticker notebook note body is invalid")
    trimmed = body.strip()
    if not trimmed:
        raise TickerNotebookError("ticker notebook note body is empty")
    if len(trimmed) > MAX_NOTE_BODY_CHARS:
        raise TickerNotebookError("ticker notebook note body exceeds bound")
    if _CONTROL_CHAR_PATTERN.search(trimmed):
        raise TickerNotebookError("ticker notebook note body has invalid control characters")
    return trimmed


class DesktopResearchNotebook:
    """Durable local operator-authored notes, isolated per canonical security_id.

    Deliberately not an AI agent, source collector, or research runner: this
    stores only plain-text operator notes and never account, holdings, OAuth,
    provider, or model data.
    """

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS iros_ticker_notebook_notes (
                    note_id TEXT PRIMARY KEY,
                    security_id TEXT NOT NULL,
                    author_role TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ticker_notebook_security
                    ON iros_ticker_notebook_notes(security_id, created_at, note_id);
                """
            )

    def add_note(self, security_id: str, body: str) -> dict[str, object]:
        normalized_security_id = _validate_security_id(security_id)
        normalized_body = _validate_body(body)
        note_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )
        record = {
            "author_role": "operator",
            "body": normalized_body,
            "created_at": created_at,
            "note_id": note_id,
            "security_id": normalized_security_id,
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO iros_ticker_notebook_notes(
                    note_id, security_id, author_role, body, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (note_id, normalized_security_id, "operator", normalized_body, created_at),
            )
        return record

    def list_notes(
        self,
        security_id: str,
        *,
        order: str = "newest",
        limit: int = MAX_NOTES_RETURNED,
    ) -> tuple[dict[str, object], ...]:
        normalized_security_id = _validate_security_id(security_id)
        if order not in {"newest", "oldest"}:
            raise TickerNotebookError("ticker notebook order is invalid")
        bounded_limit = min(max(int(limit), 0), MAX_NOTES_RETURNED)
        direction = "DESC" if order == "newest" else "ASC"
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT note_id, security_id, author_role, body, created_at
                FROM iros_ticker_notebook_notes
                WHERE security_id = ?
                ORDER BY created_at {direction}, note_id {direction}
                LIMIT ?
                """,
                (normalized_security_id, bounded_limit),
            ).fetchall()
        return tuple(
            {
                "author_role": author_role,
                "body": body,
                "created_at": created_at,
                "note_id": note_id,
                "security_id": row_security_id,
            }
            for note_id, row_security_id, author_role, body, created_at in rows
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
