from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Mapping, Protocol
from zoneinfo import ZoneInfo

from investment_research_os.evidence_bundles import EvidenceBundle
from investment_research_os.ids import stable_id
from investment_research_os.valuation_snapshots import (
    MarketSession,
    ValuationSourceReference,
    ValuationSnapshotError,
)
from investment_research_os.valuation_snapshots.massive import (
    HistoricalHaltVerification,
)


_NEW_YORK = ZoneInfo("America/New_York")
_SUPPORTED_EXCHANGES = frozenset({"NASDAQ", "NYSE", "NYSE AMERICAN"})
_VERSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*[-.]v[1-9][0-9]*$")
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_NASDAQ_TRADER_HALT_LOCATOR = (
    "https://www.nasdaqtrader.com/Trader.aspx?id=TradingHaltSearch"
)


@dataclass(frozen=True, slots=True)
class UsEquitiesSessionDefinition:
    session_date: date
    opens_at: datetime
    closes_at: datetime
    early_close: bool = False

    def __post_init__(self) -> None:
        if (
            self.opens_at.tzinfo is None
            or self.opens_at.utcoffset() is None
            or self.closes_at.tzinfo is None
            or self.closes_at.utcoffset() is None
            or self.opens_at >= self.closes_at
            or self.opens_at.astimezone(_NEW_YORK).date() != self.session_date
            or self.closes_at.astimezone(_NEW_YORK).date() != self.session_date
        ):
            raise ValueError("US equities session definition is invalid")


class VersionedUsEquitiesCalendar:
    """Fail-closed calendar backed by an explicit, versioned session schedule."""

    def __init__(
        self,
        *,
        calendar_version: str,
        coverage_start: date,
        coverage_end: date,
        sessions: tuple[UsEquitiesSessionDefinition, ...],
        closed_dates: frozenset[date] = frozenset(),
        supported_exchanges: frozenset[str] = _SUPPORTED_EXCHANGES,
    ) -> None:
        if not _VERSION_PATTERN.fullmatch(calendar_version):
            raise ValueError("market calendar version is invalid")
        if coverage_end < coverage_start:
            raise ValueError("market calendar coverage is invalid")
        if not sessions:
            raise ValueError("market calendar needs session definitions")
        if not supported_exchanges or any(
            exchange not in _SUPPORTED_EXCHANGES for exchange in supported_exchanges
        ):
            raise ValueError("market calendar exchange coverage is invalid")
        session_dates = tuple(session.session_date for session in sessions)
        if (
            tuple(sorted(session_dates)) != session_dates
            or len(set(session_dates)) != len(session_dates)
            or any(
                session_date < coverage_start or session_date > coverage_end
                for session_date in session_dates
            )
        ):
            raise ValueError("market calendar sessions are invalid")
        if any(
            closed_date < coverage_start or closed_date > coverage_end
            for closed_date in closed_dates
        ) or set(session_dates).intersection(closed_dates):
            raise ValueError("market calendar closed dates are invalid")
        expected_dates = {
            coverage_start + timedelta(days=offset)
            for offset in range((coverage_end - coverage_start).days + 1)
        }
        if set(session_dates).union(closed_dates) != expected_dates:
            raise ValueError("market calendar coverage has unclassified dates")
        self.calendar_version = calendar_version
        self.coverage_start = coverage_start
        self.coverage_end = coverage_end
        self.sessions = sessions
        self.closed_dates = closed_dates
        self.supported_exchanges = supported_exchanges
        self._cache: dict[tuple[str, datetime], MarketSession] = {}
        self._lock = threading.Lock()

    def latest_completed_session(
        self,
        primary_listing_exchange: str,
        cutoff: datetime,
    ) -> MarketSession:
        if primary_listing_exchange not in self.supported_exchanges:
            raise ValuationSnapshotError(
                "market calendar does not cover listing exchange"
            )
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValuationSnapshotError("market calendar cutoff must include timezone")
        normalized_cutoff = cutoff.astimezone(UTC)
        cutoff_market_date = cutoff.astimezone(_NEW_YORK).date()
        if not self.coverage_start <= cutoff_market_date <= self.coverage_end:
            raise ValuationSnapshotError("market calendar cutoff is outside coverage")
        cache_key = (primary_listing_exchange, normalized_cutoff)
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
            completed = tuple(
                session
                for session in self.sessions
                if session.closes_at.astimezone(UTC) <= normalized_cutoff
            )
            if not completed:
                raise ValuationSnapshotError(
                    "market calendar has no completed session for cutoff"
                )
            definition = completed[-1]
            result = MarketSession(
                session_date=definition.session_date,
                opens_at=definition.opens_at,
                closes_at=definition.closes_at,
                session_type="regular_us_trading_session",
                primary_listing_exchange=primary_listing_exchange,
                early_close=definition.early_close,
                calendar_version=self.calendar_version,
            )
            self._cache[cache_key] = result
            return result


@dataclass(frozen=True, slots=True)
class NasdaqTraderHaltSearchResult:
    query_symbol: str
    query_session_date: date
    records: tuple[Mapping[str, object], ...]
    complete: bool
    source_version: str
    source_locator: str
    retrieved_at: datetime
    response_sha256: str

    def __post_init__(self) -> None:
        if (
            not _SYMBOL_PATTERN.fullmatch(self.query_symbol)
            or not _VERSION_PATTERN.fullmatch(self.source_version)
            or self.source_locator != _NASDAQ_TRADER_HALT_LOCATOR
            or self.retrieved_at.tzinfo is None
            or self.retrieved_at.utcoffset() is None
            or not _SHA256_PATTERN.fullmatch(self.response_sha256)
        ):
            raise ValueError("Nasdaq Trader halt search result is invalid")


class NasdaqTraderHaltSearchTransport(Protocol):
    def search_halts(
        self,
        *,
        symbol: str,
        session_date: date,
    ) -> NasdaqTraderHaltSearchResult: ...


class NasdaqTraderHaltTransportError(RuntimeError):
    """Raised when Nasdaq Trader cannot prove a complete bound search."""


class HaltPriceEvidence(Protocol):
    ticker: str
    session_date: date


class NasdaqTraderHistoricalHaltVerifier:
    """Verifies historical halt state using complete Nasdaq Trader searches."""

    def __init__(
        self,
        *,
        transport: NasdaqTraderHaltSearchTransport,
        source_version: str,
        coverage_start: date,
        coverage_end: date,
        supported_exchanges: frozenset[str] = _SUPPORTED_EXCHANGES,
    ) -> None:
        if not _VERSION_PATTERN.fullmatch(source_version):
            raise ValueError("halt source version is invalid")
        if coverage_end < coverage_start:
            raise ValueError("halt source coverage is invalid")
        if not supported_exchanges or any(
            exchange not in _SUPPORTED_EXCHANGES for exchange in supported_exchanges
        ):
            raise ValueError("halt source exchange coverage is invalid")
        self.transport = transport
        self.source_version = source_version
        self.coverage_start = coverage_start
        self.coverage_end = coverage_end
        self.supported_exchanges = supported_exchanges
        self._cache: dict[tuple[str, date], NasdaqTraderHaltSearchResult] = {}
        self._lock = threading.Lock()

    def verify(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
        evidence: HaltPriceEvidence,
    ) -> str | HistoricalHaltVerification:
        symbol = bundle.security_identity.symbol
        if (
            session.primary_listing_exchange not in self.supported_exchanges
            or session.session_date < self.coverage_start
            or session.session_date > self.coverage_end
            or evidence.ticker != symbol
            or evidence.session_date != session.session_date
        ):
            return "indeterminate"
        cache_key = (symbol, session.session_date)
        with self._lock:
            result = self._cache.get(cache_key)
            if result is None:
                try:
                    result = self.transport.search_halts(
                        symbol=symbol,
                        session_date=session.session_date,
                    )
                except NasdaqTraderHaltTransportError:
                    return "indeterminate"
                self._cache[cache_key] = result
        status = self._status_from_result(
            result,
            bundle,
            session,
            bundle.as_of_cutoff,
        )
        return HistoricalHaltVerification(
            status=status,
            source_reference=ValuationSourceReference(
                source_reference_id=stable_id(
                    bundle.operator_id,
                    "personal-market-source",
                    (
                        f"{bundle.security_id}:{bundle.id}:"
                        f"{session.session_date.isoformat()}:nasdaq-trader-halts"
                    ),
                ),
                source_type="personal_market_data",
                provider="nasdaq_trader",
                locator=result.source_locator,
                published_at=None,
                retrieved_at=result.retrieved_at.astimezone(UTC),
                effective_at=bundle.as_of_cutoff,
                provider_plan_id="nasdaq_trader_public_halt_search",
                response_sha256=result.response_sha256,
                provider_contract_status="public_official_source",
                provider_limitation_codes=("historical_halt_verification_only",),
            ),
        )

    def _status_from_result(
        self,
        result: NasdaqTraderHaltSearchResult,
        bundle: EvidenceBundle,
        session: MarketSession,
        cutoff: datetime,
    ) -> str:
        symbol = bundle.security_identity.symbol
        if (
            result.query_symbol != symbol
            or result.query_session_date != session.session_date
            or result.source_version != self.source_version
            or not result.complete
        ):
            return "indeterminate"
        if not result.records:
            return "verified_not_halted"
        parsed_records: list[tuple[str, datetime, datetime | None]] = []
        expected_keys = {
            "record_id",
            "symbol",
            "market",
            "halted_at",
            "resumed_at",
            "reason_code",
        }
        for record in result.records:
            if set(record) != expected_keys:
                return "indeterminate"
            record_id = record["record_id"]
            reason_code = record["reason_code"]
            if (
                not isinstance(record_id, str)
                or not record_id.strip()
                or record["symbol"] != symbol
                or record["market"] != session.primary_listing_exchange
                or not isinstance(reason_code, str)
                or not reason_code.strip()
            ):
                return "indeterminate"
            halted_at = _parse_halt_timestamp(record["halted_at"])
            resumed_at = (
                None
                if record["resumed_at"] is None
                else _parse_halt_timestamp(record["resumed_at"])
            )
            if (
                halted_at is None
                or halted_at.astimezone(_NEW_YORK).date() != session.session_date
                or (resumed_at is not None and resumed_at <= halted_at)
            ):
                return "indeterminate"
            parsed_records.append((record_id, halted_at, resumed_at))
        record_ids = tuple(record[0] for record in parsed_records)
        if len(record_ids) != len(set(record_ids)):
            return "indeterminate"
        normalized_cutoff = cutoff.astimezone(UTC)
        if any(
            halted_at.astimezone(UTC) <= normalized_cutoff
            and (resumed_at is None or resumed_at.astimezone(UTC) > normalized_cutoff)
            for _, halted_at, resumed_at in parsed_records
        ):
            return "halted"
        return "verified_not_halted"


def _parse_halt_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


__all__ = [
    "NasdaqTraderHaltSearchResult",
    "NasdaqTraderHaltSearchTransport",
    "NasdaqTraderHaltTransportError",
    "NasdaqTraderHistoricalHaltVerifier",
    "UsEquitiesSessionDefinition",
    "VersionedUsEquitiesCalendar",
]
