from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)

from investment_research_os.evidence_bundles import EvidenceBundle
from investment_research_os.ids import stable_id
from investment_research_os.valuation_snapshots import (
    MarketSession,
    PriceObservation,
    ValuationSourceReference,
)
from investment_research_os.valuation_snapshots.composite import OfficialCloseInput
from workers.http import trusted_ssl_context
from workers.sec.storage import JsonResponse, JsonTransport

TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")


class MassiveValuationError(RuntimeError):
    """Raised when candidate Massive evidence is unavailable or invalid."""


class MassiveRateLimitError(MassiveValuationError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            f"Massive request limit reached; retry after {retry_after_seconds} seconds"
        )
        self.retry_after_seconds = retry_after_seconds


class MassiveNoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class MassiveHttpTransport:
    def __init__(
        self,
        timeout_seconds: float,
        *,
        request_executor: Callable[..., Any] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.request_executor = request_executor
        self.ssl_context = trusted_ssl_context()
        self.opener = build_opener(
            HTTPSHandler(context=self.ssl_context),
            MassiveNoRedirectHandler(),
        )

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        request = Request(
            url,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=dict(headers),
            method=method,
        )
        try:
            with self._execute(request) as response:
                return JsonResponse(
                    payload=_decode_json_body(response.read()),
                    status=response.status,
                    headers=dict(response.headers.items()),
                )
        except HTTPError as error:
            return JsonResponse(
                payload=_decode_error_json_body(error.read()),
                status=error.code,
                headers=dict(error.headers.items()) if error.headers else {},
            )
        except (TimeoutError, URLError) as error:
            raise MassiveValuationError(
                "could not reach Massive candidate provider"
            ) from error

    def _execute(self, request: Request) -> Any:
        if self.request_executor is not None:
            return self.request_executor(
                request,
                timeout=self.timeout_seconds,
                context=self.ssl_context,
            )
        return self.opener.open(request, timeout=self.timeout_seconds)


@dataclass(frozen=True, slots=True)
class MassiveSettings:
    api_key: str = field(repr=False)
    base_url: str = "https://api.massive.com"
    plan_id: str = "stocks_basic_personal"
    max_requests_per_minute: int = 5
    minimum_request_interval_seconds: float = 13.0
    cache_ttl_seconds: float = 900.0
    timeout_seconds: float = 10.0

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> MassiveSettings:
        return cls(api_key=environment.get("MASSIVE_API_KEY", ""))

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("Massive API key is required")
        if self.base_url != "https://api.massive.com":
            raise ValueError("Massive API base URL is not approved")
        if self.plan_id != "stocks_basic_personal":
            raise ValueError("Massive plan is not approved")
        if self.max_requests_per_minute != 5:
            raise ValueError("Massive Stocks Basic limit must remain five per minute")
        if self.minimum_request_interval_seconds != 13.0:
            raise ValueError("Massive request interval must remain thirteen seconds")
        if self.cache_ttl_seconds <= 0:
            raise ValueError("Massive cache TTL must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("Massive timeout must be positive")


@dataclass(frozen=True, slots=True)
class MassiveDailyCloseEvidence:
    ticker: str
    session_date: date
    open: str
    high: str
    low: str
    close: str
    volume: int
    adjustment_status: str
    provider: str
    plan_id: str
    contract_status: str
    blocking_reason_codes: tuple[str, ...]
    source_reference: str
    request_id: str | None
    retrieved_at: datetime
    response_sha256: str


@dataclass(frozen=True, slots=True)
class MassiveSplitEvent:
    event_id: str
    ticker: str
    adjustment_type: str
    execution_date: date
    split_from: str
    split_to: str


@dataclass(frozen=True, slots=True)
class MassiveSplitWindowEvidence:
    ticker: str
    start_date: date
    end_date: date
    events: tuple[MassiveSplitEvent, ...]
    provider: str
    plan_id: str
    contract_status: str
    limitation_codes: tuple[str, ...]
    source_reference: str
    request_id: str | None
    retrieved_at: datetime
    response_sha256: str


class MassiveRateLimiter(Protocol):
    def acquire(self) -> None: ...


class MassiveDailyCloseClient(Protocol):
    def fetch_daily_close(
        self,
        ticker: str,
        session_date: date,
    ) -> MassiveDailyCloseEvidence: ...


class MassiveSplitWindowClient(Protocol):
    def fetch_split_window(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> MassiveSplitWindowEvidence: ...


@dataclass(frozen=True, slots=True)
class HistoricalHaltVerification:
    status: str
    source_reference: ValuationSourceReference

    def __post_init__(self) -> None:
        if self.status not in {
            "verified_not_halted",
            "halted",
            "indeterminate",
        }:
            raise ValueError("historical halt verification status is invalid")
        if self.source_reference.source_type != "personal_market_data":
            raise ValueError("historical halt source reference is invalid")


class HistoricalHaltVerifier(Protocol):
    def verify(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
        evidence: MassiveDailyCloseEvidence,
    ) -> str | HistoricalHaltVerification: ...


class MassivePersonalResearchCloseAdapter:
    """Maps Massive EOD bars into lower-assurance personal-research inputs."""

    def __init__(
        self,
        *,
        client: MassiveDailyCloseClient,
        halt_verifier: HistoricalHaltVerifier,
    ) -> None:
        self.client = client
        self.halt_verifier = halt_verifier

    def load(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
    ) -> OfficialCloseInput:
        evidence = self.client.fetch_daily_close(
            bundle.security_identity.symbol,
            session.session_date,
        )
        if (
            evidence.ticker != bundle.security_identity.symbol
            or evidence.session_date != session.session_date
            or evidence.adjustment_status != "split_unadjusted"
        ):
            raise MassiveValuationError(
                "Massive personal research close identity is invalid"
            )
        halt_verification = self.halt_verifier.verify(bundle, session, evidence)
        if isinstance(halt_verification, HistoricalHaltVerification):
            halt_status = halt_verification.status
            halt_source_references = (halt_verification.source_reference,)
        else:
            halt_status = halt_verification
            halt_source_references = ()
        if halt_status not in {
            "verified_not_halted",
            "halted",
            "indeterminate",
        }:
            raise MassiveValuationError(
                "Massive personal research halt verification is invalid"
            )
        source_reference_id = stable_id(
            bundle.operator_id,
            "personal-market-source",
            f"{bundle.security_id}:{session.session_date.isoformat()}:massive",
        )
        return OfficialCloseInput(
            prices=(
                PriceObservation(
                    price_type="verified_consolidated_end_of_day_close",
                    session_type=session.session_type,
                    session_date=session.session_date,
                    primary_listing_exchange=session.primary_listing_exchange,
                    price=evidence.close,
                    currency="USD",
                    official_close_timestamp=session.closes_at,
                    market_status=("halted" if halt_status == "halted" else "closed"),
                    corporate_action_adjustment_status="unadjusted",
                    provider=evidence.provider,
                    source_reference=source_reference_id,
                    halt_verification_status=halt_status,
                ),
            ),
            source_references=(
                ValuationSourceReference(
                    source_reference_id=source_reference_id,
                    source_type="personal_market_data",
                    provider=evidence.provider,
                    locator=evidence.source_reference,
                    published_at=None,
                    retrieved_at=evidence.retrieved_at,
                    effective_at=session.closes_at,
                    provider_plan_id=evidence.plan_id,
                    response_sha256=evidence.response_sha256,
                    provider_contract_status=evidence.contract_status,
                    provider_limitation_codes=evidence.blocking_reason_codes,
                ),
                *halt_source_references,
            ),
        )


class MassiveRollingRateLimiter:
    def __init__(
        self,
        *,
        max_requests: int = 5,
        window_seconds: float = 60.0,
        minimum_interval_seconds: float = 13.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_requests != 5:
            raise ValueError("Massive limiter must preserve five request capacity")
        if window_seconds < 60:
            raise ValueError("Massive limiter window must be at least sixty seconds")
        if minimum_interval_seconds < 13:
            raise ValueError("Massive limiter interval must preserve safety margin")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.minimum_interval_seconds = minimum_interval_seconds
        self.clock = clock
        self.sleeper = sleeper
        self._request_starts: deque[float] = deque()
        self._last_request_start: float | None = None
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self.clock()
            if self._last_request_start is not None:
                interval_wait = self.minimum_interval_seconds - (
                    now - self._last_request_start
                )
                if interval_wait > 0:
                    self.sleeper(interval_wait)
                    now = self.clock()

            self._discard_expired(now)
            if len(self._request_starts) >= self.max_requests:
                window_wait = (
                    self.window_seconds - (now - self._request_starts[0]) + 0.001
                )
                if window_wait > 0:
                    self.sleeper(window_wait)
                    now = self.clock()
                self._discard_expired(now)

            self._request_starts.append(now)
            self._last_request_start = now

    def _discard_expired(self, now: float) -> None:
        while (
            self._request_starts
            and now - self._request_starts[0] >= self.window_seconds
        ):
            self._request_starts.popleft()


class MassiveRequestCoordinator:
    def __init__(
        self,
        rate_limiter: MassiveRateLimiter | None = None,
    ) -> None:
        self.rate_limiter = rate_limiter or MassiveRollingRateLimiter()
        self.lock = threading.Lock()
        self.daily_close_cache: dict[
            str,
            tuple[float, MassiveDailyCloseEvidence],
        ] = {}
        self.split_window_cache: dict[
            str,
            tuple[float, MassiveSplitWindowEvidence],
        ] = {}
        self.blocked_until = 0.0

    def block_for(self, *, now: float, seconds: int) -> None:
        self.blocked_until = max(self.blocked_until, now + seconds)

    def cooldown_remaining(self, *, now: float) -> int | None:
        if now >= self.blocked_until:
            return None
        return max(1, math.ceil(self.blocked_until - now))


_PROCESS_COORDINATOR_LOCK = threading.Lock()
_PROCESS_REQUEST_COORDINATORS: dict[str, MassiveRequestCoordinator] = {}


def _process_request_coordinator(
    settings: MassiveSettings,
) -> MassiveRequestCoordinator:
    fingerprint = hashlib.sha256(
        "\x00".join(
            (
                settings.api_key,
                settings.plan_id,
                settings.base_url,
            )
        ).encode()
    ).hexdigest()
    with _PROCESS_COORDINATOR_LOCK:
        existing = _PROCESS_REQUEST_COORDINATORS.get(fingerprint)
        if existing is not None:
            return existing
        coordinator = MassiveRequestCoordinator(
            MassiveRollingRateLimiter(
                max_requests=settings.max_requests_per_minute,
                minimum_interval_seconds=(settings.minimum_request_interval_seconds),
            )
        )
        _PROCESS_REQUEST_COORDINATORS[fingerprint] = coordinator
        return coordinator


class MassiveValuationClient:
    def __init__(
        self,
        settings: MassiveSettings,
        *,
        transport: JsonTransport | None = None,
        rate_limiter: MassiveRateLimiter | None = None,
        request_coordinator: MassiveRequestCoordinator | None = None,
        clock: Callable[[], datetime] | None = None,
        cache_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if rate_limiter is not None and request_coordinator is not None:
            raise ValueError(
                "provide either rate_limiter or request_coordinator, not both"
            )
        self.settings = settings
        self.transport = transport or MassiveHttpTransport(settings.timeout_seconds)
        self.request_coordinator = request_coordinator or (
            MassiveRequestCoordinator(rate_limiter)
            if rate_limiter is not None
            else _process_request_coordinator(settings)
        )
        self.rate_limiter = self.request_coordinator.rate_limiter
        self.clock = clock or (lambda: datetime.now(UTC))
        self.cache_clock = cache_clock
        self._daily_close_cache = self.request_coordinator.daily_close_cache
        self._split_window_cache = self.request_coordinator.split_window_cache

    def fetch_daily_close(
        self,
        ticker: str,
        session_date: date,
    ) -> MassiveDailyCloseEvidence:
        with self.request_coordinator.lock:
            cache_now = self.cache_clock()
            self._purge_expired_cache(cache_now)
            return self._fetch_daily_close_serialized(
                ticker,
                session_date,
                cache_now=cache_now,
            )

    def fetch_split_window(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> MassiveSplitWindowEvidence:
        with self.request_coordinator.lock:
            cache_now = self.cache_clock()
            self._purge_expired_cache(cache_now)
            return self._fetch_split_window_serialized(
                ticker,
                start_date,
                end_date,
                cache_now=cache_now,
            )

    def _fetch_split_window_serialized(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        *,
        cache_now: float,
    ) -> MassiveSplitWindowEvidence:
        normalized_ticker = ticker.strip().upper()
        if not TICKER_PATTERN.fullmatch(normalized_ticker):
            raise ValueError("ticker has invalid format")
        if start_date > end_date:
            raise ValueError("Massive split window is invalid")
        query = urlencode(
            {
                "ticker": normalized_ticker,
                "execution_date.gte": start_date.isoformat(),
                "execution_date.lte": end_date.isoformat(),
                "sort": "execution_date.asc",
                "limit": "100",
            }
        )
        source_reference = f"{self.settings.base_url}/stocks/v1/splits?{query}"
        cached = self._split_window_cache.get(source_reference)
        if cached is not None and cache_now < cached[0]:
            return cached[1]
        cooldown_remaining = self.request_coordinator.cooldown_remaining(now=cache_now)
        if cooldown_remaining is not None:
            raise MassiveRateLimitError(cooldown_remaining)
        self.rate_limiter.acquire()
        response = self.transport.request_json(
            "GET",
            source_reference,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.settings.api_key}",
            },
        )
        if response.status == 429:
            retry_after_seconds = _retry_after_seconds(
                response.headers,
                now=self.clock(),
            )
            self.request_coordinator.block_for(
                now=self.cache_clock(),
                seconds=retry_after_seconds,
            )
            raise MassiveRateLimitError(retry_after_seconds)
        if response.status != 200:
            raise MassiveValuationError(
                f"Massive split window returned HTTP {response.status}"
            )
        payload = response.payload
        if (
            not isinstance(payload, dict)
            or payload.get("status") != "OK"
            or payload.get("next_url") not in (None, "")
            or not isinstance(payload.get("results"), list)
        ):
            raise MassiveValuationError("Massive split window response is invalid")
        events = tuple(
            _parse_split_event(
                item,
                ticker=normalized_ticker,
                start_date=start_date,
                end_date=end_date,
            )
            for item in payload["results"]
        )
        if (
            tuple(sorted(events, key=lambda item: (item.execution_date, item.event_id)))
            != events
        ):
            raise MassiveValuationError("Massive split window order is invalid")
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise RuntimeError("Massive clock must return timezone-aware timestamp")
        canonical_payload = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        request_id = payload.get("request_id")
        evidence = MassiveSplitWindowEvidence(
            ticker=normalized_ticker,
            start_date=start_date,
            end_date=end_date,
            events=events,
            provider="massive_stocks_basic_candidate",
            plan_id=self.settings.plan_id,
            contract_status="candidate_unapproved",
            limitation_codes=(
                "corporate_action_coverage_candidate",
                "persistence_rights_unconfirmed",
                "authenticated_display_rights_unconfirmed",
            ),
            source_reference=source_reference,
            request_id=request_id if isinstance(request_id, str) else None,
            retrieved_at=retrieved_at.astimezone(UTC),
            response_sha256=hashlib.sha256(canonical_payload).hexdigest(),
        )
        self._split_window_cache[source_reference] = (
            cache_now + self.settings.cache_ttl_seconds,
            evidence,
        )
        return evidence

    def _fetch_daily_close_serialized(
        self,
        ticker: str,
        session_date: date,
        *,
        cache_now: float,
    ) -> MassiveDailyCloseEvidence:
        normalized_ticker = ticker.strip().upper()
        if not TICKER_PATTERN.fullmatch(normalized_ticker):
            raise ValueError("ticker has invalid format")
        encoded_ticker = quote(normalized_ticker, safe="")
        session_text = session_date.isoformat()
        source_reference = (
            f"{self.settings.base_url}/v1/open-close/"
            f"{encoded_ticker}/{session_text}?adjusted=false"
        )
        cached = self._daily_close_cache.get(source_reference)
        if cached is not None and cache_now < cached[0]:
            return cached[1]
        cooldown_remaining = self.request_coordinator.cooldown_remaining(now=cache_now)
        if cooldown_remaining is not None:
            raise MassiveRateLimitError(cooldown_remaining)
        self.rate_limiter.acquire()
        response = self.transport.request_json(
            "GET",
            source_reference,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.settings.api_key}",
            },
        )
        if response.status == 429:
            retry_after_seconds = _retry_after_seconds(
                response.headers,
                now=self.clock(),
            )
            self.request_coordinator.block_for(
                now=self.cache_clock(),
                seconds=retry_after_seconds,
            )
            raise MassiveRateLimitError(retry_after_seconds)
        if response.status != 200:
            raise MassiveValuationError(
                f"Massive daily close returned HTTP {response.status}"
            )
        if not isinstance(response.payload, dict):
            raise MassiveValuationError("Massive daily close response is invalid")
        payload = response.payload
        if (
            payload.get("status") != "OK"
            or str(payload.get("symbol", "")).strip().upper() != normalized_ticker
            or payload.get("from") != session_text
        ):
            raise MassiveValuationError("Massive daily close identity is invalid")
        open_price = _positive_decimal(payload.get("open"), "open")
        high = _positive_decimal(payload.get("high"), "high")
        low = _positive_decimal(payload.get("low"), "low")
        close = _positive_decimal(payload.get("close"), "close")
        if high < max(open_price, low, close) or low > min(
            open_price,
            high,
            close,
        ):
            raise MassiveValuationError("Massive daily close range is invalid")
        raw_volume = payload.get("volume")
        if (
            isinstance(raw_volume, bool)
            or not isinstance(raw_volume, int)
            or raw_volume < 0
        ):
            raise MassiveValuationError("Massive daily close volume is invalid")
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise RuntimeError("Massive clock must return timezone-aware timestamp")
        canonical_payload = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        request_id = payload.get("request_id")
        evidence = MassiveDailyCloseEvidence(
            ticker=normalized_ticker,
            session_date=session_date,
            open=_decimal_text(open_price),
            high=_decimal_text(high),
            low=_decimal_text(low),
            close=_decimal_text(close),
            volume=raw_volume,
            adjustment_status="split_unadjusted",
            provider="massive_stocks_basic_candidate",
            plan_id=self.settings.plan_id,
            contract_status="candidate_unapproved",
            blocking_reason_codes=(
                "official_close_provenance_unconfirmed",
                "official_close_timestamp_unavailable",
                "historical_halt_status_unavailable",
                "corporate_action_coverage_incomplete",
                "persistence_rights_unconfirmed",
                "authenticated_display_rights_unconfirmed",
            ),
            source_reference=source_reference,
            request_id=request_id if isinstance(request_id, str) else None,
            retrieved_at=retrieved_at.astimezone(UTC),
            response_sha256=hashlib.sha256(canonical_payload).hexdigest(),
        )
        self._daily_close_cache[source_reference] = (
            cache_now + self.settings.cache_ttl_seconds,
            evidence,
        )
        return evidence

    def _purge_expired_cache(self, cache_now: float) -> None:
        expired = [
            key
            for key, (expires_at, _) in self._daily_close_cache.items()
            if cache_now >= expires_at
        ]
        for key in expired:
            del self._daily_close_cache[key]
        expired_split_windows = [
            key
            for key, (expires_at, _) in self._split_window_cache.items()
            if cache_now >= expires_at
        ]
        for key in expired_split_windows:
            del self._split_window_cache[key]


def _parse_split_event(
    value: object,
    *,
    ticker: str,
    start_date: date,
    end_date: date,
) -> MassiveSplitEvent:
    if not isinstance(value, dict):
        raise MassiveValuationError("Massive split event is invalid")
    event_id = value.get("id")
    event_ticker = value.get("ticker")
    adjustment_type = value.get("adjustment_type")
    execution_text = value.get("execution_date")
    if (
        not isinstance(event_id, str)
        or not event_id.strip()
        or event_ticker != ticker
        or adjustment_type not in {"forward_split", "reverse_split"}
        or not isinstance(execution_text, str)
    ):
        raise MassiveValuationError("Massive split event identity is invalid")
    try:
        execution_date = date.fromisoformat(execution_text)
        split_from = _positive_decimal(value.get("split_from"), "split_from")
        split_to = _positive_decimal(value.get("split_to"), "split_to")
    except ValueError as error:
        raise MassiveValuationError("Massive split event is invalid") from error
    if not start_date <= execution_date <= end_date:
        raise MassiveValuationError("Massive split event is outside requested window")
    if (
        adjustment_type == "forward_split"
        and split_to <= split_from
        or adjustment_type == "reverse_split"
        and split_to >= split_from
    ):
        raise MassiveValuationError("Massive split ratio is invalid")
    return MassiveSplitEvent(
        event_id=event_id,
        ticker=ticker,
        adjustment_type=adjustment_type,
        execution_date=execution_date,
        split_from=_decimal_text(split_from),
        split_to=_decimal_text(split_to),
    )


def _positive_decimal(value: object, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise MassiveValuationError(
            f"Massive daily close {label} is invalid"
        ) from error
    if not parsed.is_finite() or parsed <= 0:
        raise MassiveValuationError(f"Massive daily close {label} is invalid")
    return parsed


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _decode_json_body(raw: bytes) -> object:
    if not raw:
        return None
    try:
        return json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MassiveValuationError(
            "Massive candidate response was not valid JSON"
        ) from error


def _decode_error_json_body(raw: bytes) -> object:
    try:
        return _decode_json_body(raw)
    except MassiveValuationError:
        return None


def _retry_after_seconds(
    headers: object,
    *,
    now: datetime | None = None,
) -> int:
    if not isinstance(headers, Mapping):
        return 60
    raw_value = next(
        (value for key, value in headers.items() if str(key).lower() == "retry-after"),
        None,
    )
    try:
        parsed = int(str(raw_value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(str(raw_value))
        except (TypeError, ValueError):
            return 60
        if retry_at.tzinfo is None or retry_at.utcoffset() is None:
            return 60
        reference = now or datetime.now(UTC)
        if reference.tzinfo is None or reference.utcoffset() is None:
            return 60
        return max(
            1,
            math.ceil(
                (retry_at.astimezone(UTC) - reference.astimezone(UTC)).total_seconds()
            ),
        )
    return max(1, parsed)


__all__ = [
    "HistoricalHaltVerification",
    "HistoricalHaltVerifier",
    "MassiveDailyCloseClient",
    "MassiveDailyCloseEvidence",
    "MassiveHttpTransport",
    "MassiveNoRedirectHandler",
    "MassivePersonalResearchCloseAdapter",
    "MassiveRollingRateLimiter",
    "MassiveRateLimitError",
    "MassiveRequestCoordinator",
    "MassiveSettings",
    "MassiveSplitEvent",
    "MassiveSplitWindowClient",
    "MassiveSplitWindowEvidence",
    "MassiveValuationClient",
    "MassiveValuationError",
]
