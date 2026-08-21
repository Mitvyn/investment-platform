from __future__ import annotations

import re
import sqlite3
from pathlib import Path


_TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_MOOMOO_US_SYMBOL_PATTERN = re.compile(r"^US\.([A-Z][A-Z0-9.-]{0,9})$")
_VALID_SOURCES = {"manual", "moomoo_position"}


class DesktopSecurityRegistry:
    """Small desktop-local ticker index with no account or position values."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS iros_desktop_security_registry (
                    ticker TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS iros_desktop_security_registry_sources (
                    ticker TEXT NOT NULL REFERENCES iros_desktop_security_registry(ticker)
                        ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    PRIMARY KEY (ticker, source)
                );
                """
            )

    def add_manual_ticker(self, ticker: str) -> None:
        self._add(ticker, source="manual")

    def import_moomoo_symbols(self, symbols: tuple[str, ...]) -> None:
        for symbol in symbols:
            match = _MOOMOO_US_SYMBOL_PATTERN.fullmatch(symbol.strip().upper())
            if match is not None:
                self._add(match.group(1), source="moomoo_position")

    def list_entries(self) -> tuple[dict[str, object], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT registry.ticker, source.source
                FROM iros_desktop_security_registry AS registry
                JOIN iros_desktop_security_registry_sources AS source
                  ON source.ticker = registry.ticker
                ORDER BY registry.ticker ASC, source.source ASC
                """
            ).fetchall()
        grouped: dict[str, list[str]] = {}
        for ticker, source in rows:
            grouped.setdefault(str(ticker), []).append(str(source))
        return tuple(
            {"ticker": ticker, "sources": tuple(sources)}
            for ticker, sources in grouped.items()
        )

    def _add(self, ticker: str, *, source: str) -> None:
        normalized = ticker.strip().upper()
        if not _TICKER_PATTERN.fullmatch(normalized):
            raise ValueError("desktop security registry ticker is invalid")
        if source not in _VALID_SOURCES:
            raise ValueError("desktop security registry source is invalid")
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO iros_desktop_security_registry(ticker) VALUES (?)",
                (normalized,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO iros_desktop_security_registry_sources(ticker, source)
                VALUES (?, ?)
                """,
                (normalized, source),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
