"""Live historical transports and the acquisition path that consumes them.

``LiveQuantSource`` is provider-agnostic: it accepts any
:class:`~workers.quant_sources.transports.HistoricalTransport`, checks what the
transport returned against what the caller asked for, and hands the result to
the offline Quant acquisition boundary. It never fetches anything itself.

Two transports live here. The yfinance one is real, bounded, and unadjusted.
The Moomoo one is a typed stub that fails with a stated blocker, because the
historical-bar endpoint and response semantics have not been verified against
official documentation and a guessed endpoint would produce a receipt that
looks authoritative and is not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from investment_research_os.quant import PointInTimeDataset, QuantContractError
from investment_research_os.quant_sources import (
    SourceSnapshot,
    acquire_point_in_time_dataset,
    payload_sha256,
)
from workers.market.client import YFinanceSettings
from workers.quant_sources.transports import (
    BoundedCaller,
    HistoricalTransport,
    HistoryBar,
    HistoryPayload,
    RateLimit,
    RetryPolicy,
    TransientTransportError,
    TransportBlockedError,
    TransportError,
)

YFINANCE_PROVIDER_ID = "yahoo_finance_via_yfinance"
MOOMOO_PROVIDER_ID = "moomoo_openapi"

#: Yahoo publishes no personal-use quota, so this is a self-imposed ceiling
#: chosen to stay far below any plausible throttle rather than to match one.
YFINANCE_RATE_LIMIT = RateLimit(max_calls=5, per_seconds=60.0)
YFINANCE_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    backoff_seconds=2.0,
    backoff_multiplier=2.0,
    max_backoff_seconds=16.0,
)

YFINANCE_WINDOW_BLOCKER = (
    "yfinance live acquisition is blocked. The transport requests a window "
    "bounded by the point-in-time cutoff, and including the cutoff session "
    "depends on whether yfinance treats end as exclusive. That behaviour has "
    "not been confirmed against official documentation, and this session "
    "cannot reach the network to confirm it. If the assumption is wrong every "
    "receipt is one session short or one session long, which is a silent "
    "point-in-time error rather than a loud one. Confirm the end-boundary "
    "semantics against official documentation, register the pinned evidence "
    "record in WINDOW_SEMANTICS_REGISTRY, and pass the resulting "
    "WindowSemanticsPolicy. No free-form reference, plausible policy name, or "
    "test-scoped fixture can unblock a live fetch. A verified record exists for "
    "yfinance 1.5.1; see yfinance_end_exclusive_policy."
)

MOOMOO_HISTORY_BLOCKER = (
    "Moomoo historical daily-bar acquisition is blocked. The Web API "
    "historical-bar route, request parameters, pagination behaviour, "
    "adjustment semantics, and corporate-action representation have not been "
    "verified against official documentation, and this repository holds no "
    "evidence of a verified historical endpoint. Implementing a guessed route "
    "would produce point-in-time receipts that look authoritative while "
    "resting on an unverified price basis, which is the one failure this "
    "boundary exists to prevent. Verify the endpoint and response semantics "
    "against official documentation first, then implement fetch_daily_history "
    "to return a HistoryPayload; nothing above this transport changes."
)


@dataclass(frozen=True, slots=True)
class WindowSemanticsPolicy:
    """One claim about a provider's history-window boundary, with its evidence.

    ``end_is_exclusive`` decides whether the cutoff session is included in a
    receipt. It is a point-in-time correctness fact, not a preference, so it may
    not be asserted by whoever happens to be calling. A policy is only honoured
    if its ID is registered in :data:`WINDOW_SEMANTICS_REGISTRY` and its pinned
    evidence digest and boundary claim both match what was registered.

    The evidence digest pins the documentation that was read. It does not prove
    the documentation says what the registrant claims; it proves that the claim
    has not drifted from the artifact it was recorded against, and that nobody
    edited the boundary flag afterwards.
    """

    policy_id: str
    end_is_exclusive: bool
    evidence_sha256: str
    verified_on: date

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise TransportError("policy_id must be a non-empty string")
        if type(self.end_is_exclusive) is not bool:
            raise TransportError("end_is_exclusive must be a boolean")
        digest = self.evidence_sha256
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or not set(digest) <= frozenset("0123456789abcdef")
        ):
            raise TransportError(
                "evidence_sha256 must be a lowercase 64-character SHA-256 digest"
            )
        if type(self.verified_on) is not date:
            raise TransportError("verified_on must be a date")


@dataclass(frozen=True, slots=True)
class _RegisteredPolicy:
    """What the registry pins for one policy ID.

    Everything a caller could otherwise assert for itself is pinned here and
    checked against the policy it presents: the evidence digest, the boundary
    claim, the date the claim was verified, and the library version the claim
    was verified against. A policy may restate these; it may not choose them.

    ``library_version`` matters as much as the boundary. The evidence is a
    docstring in one tagged release. A policy verified against that release
    says nothing about another, so a transport pinning a different version is
    refused rather than allowed to inherit the finding.
    """

    evidence_sha256: str
    end_is_exclusive: bool
    scope: str
    note: str
    verified_on: date
    library_version: str
    evidence_urls: tuple[str, ...] = ()


#: The fixture policy. Its scope is ``test``, which the transport refuses on any
#: path that could reach a provider. It exists so offline mapping tests can run
#: without inventing a plausible-looking verified policy, which is exactly the
#: thing an adversarial caller would do.
TEST_WINDOW_SEMANTICS_POLICY_ID = "test-fixture-unverified-window-semantics"
TEST_WINDOW_SEMANTICS_EVIDENCE = (
    b"investment-research-os/test-fixture/yfinance-window-semantics/unverified"
)
TEST_WINDOW_SEMANTICS_EVIDENCE_SHA256 = hashlib.sha256(
    TEST_WINDOW_SEMANTICS_EVIDENCE
).hexdigest()
_TEST_LIBRARY_VERSION = "1.5.1"

#: The verified yfinance boundary finding.
#:
#: The digest is over the exact quoted docstring recorded in collaboration
#: response 2026-08-18-030, reproduced there byte for byte so anyone can
#: recompute it. It is a hash of the recorded quotation, not of the upstream
#: file: the fetch path returns processed text rather than the served bytes, so
#: a file digest would pin a rendering and could not be reproduced by a
#: reviewer. The digest attests to what was read; the URLs say where.
YFINANCE_END_EXCLUSIVE_POLICY_ID = "yfinance-1-5-1-end-exclusive"
YFINANCE_END_EXCLUSIVE_EVIDENCE_SHA256 = (
    "acd3af838820bcfd3ebf8bda972712c32868577c3494f58151cd6ae0a5ac665c"
)
YFINANCE_END_EXCLUSIVE_VERIFIED_ON = date(2026, 8, 17)

#: Read-only on purpose. A mutable registry would let any caller register the
#: policy it wants and satisfy the allowlist it just wrote.
#:
#: One verified entry exists: the yfinance end-boundary finding from
#: collaboration response 2026-08-18-030. It authorizes a live fetch only for a
#: transport pinning library version 1.5.1, which is the release its evidence
#: was read from. Every other provider and version remains blocked by the
#: absence of a record rather than by a flag someone could flip.
WINDOW_SEMANTICS_REGISTRY: Mapping[str, _RegisteredPolicy] = MappingProxyType(
    {
        TEST_WINDOW_SEMANTICS_POLICY_ID: _RegisteredPolicy(
            evidence_sha256=TEST_WINDOW_SEMANTICS_EVIDENCE_SHA256,
            end_is_exclusive=True,
            scope="test",
            note=(
                "Fixture only. Records the untested assumption that yfinance "
                "treats end as exclusive. Not evidence of anything."
            ),
            verified_on=date(2026, 8, 17),
            library_version=_TEST_LIBRARY_VERSION,
        ),
        YFINANCE_END_EXCLUSIVE_POLICY_ID: _RegisteredPolicy(
            evidence_sha256=YFINANCE_END_EXCLUSIVE_EVIDENCE_SHA256,
            end_is_exclusive=True,
            scope="verified",
            note=(
                "yfinance 1.5.1 PriceHistory.history docstring states that end "
                "is exclusive, with the worked example end=2023-01-01 yielding "
                "a last data point of 2022-12-31. Verified 2026-08-17 against "
                "the source at tag 1.5.1, the source at main, and the official "
                "documentation site. Documentary verification only: no live "
                "yfinance call was made. See collaboration response "
                "2026-08-18-030."
            ),
            verified_on=date(2026, 8, 17),
            library_version="1.5.1",
            evidence_urls=(
                "https://raw.githubusercontent.com/ranaroussi/yfinance/1.5.1"
                "/yfinance/scrapers/history.py",
                "https://raw.githubusercontent.com/ranaroussi/yfinance/main"
                "/yfinance/scrapers/history.py",
                "https://ranaroussi.github.io/yfinance/reference"
                "/yfinance.price_history.html",
            ),
        ),
    }
)


def test_window_semantics_policy() -> WindowSemanticsPolicy:
    """The one policy offline tests may use. Refused on any live path."""

    return WindowSemanticsPolicy(
        policy_id=TEST_WINDOW_SEMANTICS_POLICY_ID,
        end_is_exclusive=True,
        evidence_sha256=TEST_WINDOW_SEMANTICS_EVIDENCE_SHA256,
        verified_on=date(2026, 8, 17),
    )


def yfinance_end_exclusive_policy() -> WindowSemanticsPolicy:
    """The verified yfinance boundary policy, restating the pinned record."""

    return WindowSemanticsPolicy(
        policy_id=YFINANCE_END_EXCLUSIVE_POLICY_ID,
        end_is_exclusive=True,
        evidence_sha256=YFINANCE_END_EXCLUSIVE_EVIDENCE_SHA256,
        verified_on=YFINANCE_END_EXCLUSIVE_VERIFIED_ON,
    )


def authorize_window_semantics(
    policy: object,
    *,
    allow_test_scope: bool,
    live_path: bool,
    library_version: str | None = None,
) -> _RegisteredPolicy:
    """Resolve a policy against the registry, or refuse.

    Fails closed in every direction: a non-policy object, an unregistered ID, a
    digest that does not match the pinned record, a boundary claim that does not
    match the pinned record, a verification date that does not match the pinned
    record, a library version the record was not verified against, a test-scoped
    policy without the explicit test opt-in, and a test-scoped policy on a path
    that could reach a provider.

    ``TransportBlockedError`` is used throughout rather than ``TransportError``,
    because none of these are retryable conditions: they are all missing
    authorization.
    """

    if not isinstance(policy, WindowSemanticsPolicy):
        raise TransportBlockedError(YFINANCE_WINDOW_BLOCKER)
    registered = WINDOW_SEMANTICS_REGISTRY.get(policy.policy_id)
    if registered is None:
        raise TransportBlockedError(
            f"window semantics policy {policy.policy_id!r} is not registered. "
            + YFINANCE_WINDOW_BLOCKER
        )
    if policy.evidence_sha256 != registered.evidence_sha256:
        raise TransportBlockedError(
            f"window semantics policy {policy.policy_id!r} does not match its "
            "pinned evidence digest. " + YFINANCE_WINDOW_BLOCKER
        )
    if policy.end_is_exclusive != registered.end_is_exclusive:
        raise TransportBlockedError(
            f"window semantics policy {policy.policy_id!r} claims a different "
            "end boundary than the pinned record. " + YFINANCE_WINDOW_BLOCKER
        )
    if policy.verified_on != registered.verified_on:
        raise TransportBlockedError(
            f"window semantics policy {policy.policy_id!r} claims verification "
            f"on {policy.verified_on.isoformat()}, but the pinned record was "
            f"verified on {registered.verified_on.isoformat()}. "
            + YFINANCE_WINDOW_BLOCKER
        )
    if library_version is not None and library_version != registered.library_version:
        raise TransportBlockedError(
            f"window semantics policy {policy.policy_id!r} was verified against "
            f"library version {registered.library_version!r}, not the pinned "
            f"{library_version!r}; a finding read from one release proves "
            "nothing about another. " + YFINANCE_WINDOW_BLOCKER
        )
    if registered.scope == "test":
        if not allow_test_scope:
            raise TransportBlockedError(
                "a test-scoped window semantics policy requires an explicit "
                "test opt-in. " + YFINANCE_WINDOW_BLOCKER
            )
        if live_path:
            raise TransportBlockedError(
                "a test-scoped window semantics policy may never authorize a "
                "live fetch. " + YFINANCE_WINDOW_BLOCKER
            )
    elif registered.scope != "verified":
        raise TransportBlockedError(
            f"window semantics scope {registered.scope!r} is not recognized. "
            + YFINANCE_WINDOW_BLOCKER
        )
    return registered


@dataclass(frozen=True, slots=True)
class LiveAcquisition:
    """One checked provider fetch, and the exact rows its receipt was built from.

    The receipt's own bar values have already been through Quant's Decimal
    normalisation and no longer match the provider's declared text, so they
    cannot be replayed into a ``quant_local_dataset.v1`` document and expected
    to reproduce ``dataset.source_content_sha256``. ``bar_rows`` and
    ``split_rows`` are the provider's declared values before that
    normalisation, which is what a caller needing to persist a document
    alongside the receipt must use instead.
    """

    dataset: PointInTimeDataset
    bar_rows: tuple[dict[str, object], ...]
    split_rows: tuple[dict[str, object], ...]


class LiveQuantSource:
    """Turn one transport's daily history into one Quant point-in-time receipt.

    The transport is injected, so every rule below is testable without a
    provider. What arrives is checked against what was requested rather than
    trusted: a payload naming another symbol, another currency, or a session
    after the cutoff is refused, never reconciled or truncated.
    """

    def __init__(self, transport: HistoricalTransport) -> None:
        self.transport = transport

    def acquire(
        self,
        *,
        ticker: str,
        security_id: str,
        as_of_cutoff: date,
        start: date,
        currency: str | None = None,
    ) -> PointInTimeDataset:
        return self._acquire(
            ticker=ticker,
            security_id=security_id,
            as_of_cutoff=as_of_cutoff,
            currency=currency,
            start=start,
        ).dataset

    def acquire_with_rows(
        self,
        *,
        ticker: str,
        security_id: str,
        as_of_cutoff: date,
        start: date,
        currency: str | None = None,
    ) -> LiveAcquisition:
        """Like :meth:`acquire`, but also returns the rows behind the receipt.

        Only a caller that must persist a ``quant_local_dataset.v1`` document
        alongside the receipt, so it can be reloaded and re-validated after a
        restart, needs this. Every other caller should keep using
        :meth:`acquire`.
        """

        return self._acquire(
            ticker=ticker,
            security_id=security_id,
            as_of_cutoff=as_of_cutoff,
            currency=currency,
            start=start,
        )

    def _acquire(
        self,
        *,
        ticker: str,
        security_id: str,
        as_of_cutoff: date,
        currency: str | None,
        start: date,
    ) -> LiveAcquisition:
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            raise TransportError("ticker is required")
        if type(as_of_cutoff) is not date or type(start) is not date:
            raise TransportError("start and as_of_cutoff must be dates")
        if start > as_of_cutoff:
            raise TransportError(
                f"start {start.isoformat()} is after the cutoff "
                f"{as_of_cutoff.isoformat()}"
            )

        payload = self.transport.fetch_daily_history(
            normalized_ticker,
            start=start,
            end=as_of_cutoff,
        )
        if not isinstance(payload, HistoryPayload):
            raise TransportError(
                f"transport must return a HistoryPayload, got "
                f"{type(payload).__name__}"
            )
        # The payload names its own provider, and the transport names the
        # provider it is. A mismatch means the receipt would be stamped with a
        # source that did not produce it, which is the one provenance field
        # nothing downstream can check.
        declared = getattr(self.transport, "provider_id", None)
        if not isinstance(declared, str) or not declared.strip():
            raise TransportError(
                "transport must declare a non-empty provider_id"
            )
        if payload.provider_id != declared:
            raise TransportError(
                f"payload provider {payload.provider_id!r} does not match the "
                f"transport provider {declared!r}"
            )
        if payload.symbol.strip().upper() != normalized_ticker:
            raise TransportError(
                f"transport returned a different symbol {payload.symbol!r}"
            )
        # A caller that already knows the currency it expects (for example,
        # one replaying a receipt it validated before) may assert it here and
        # have a mismatch refused. A caller with no independent currency of
        # its own, such as a fresh provider fetch, passes none and simply
        # takes the provider's own declared currency, which ``HistoryPayload``
        # has already checked is a well-formed ISO 4217 code. Neither path
        # ever assumes or defaults a currency.
        if currency is not None and payload.currency != currency:
            raise TransportError(
                f"transport currency {payload.currency!r} does not match the "
                f"requested currency {currency!r}"
            )
        if not payload.bars:
            raise TransportError("transport returned no daily bars")

        bar_rows, split_rows = _rows(payload, start=start, as_of_cutoff=as_of_cutoff)
        try:
            snapshot = SourceSnapshot(
                source_id=payload.provider_id,
                source_revision=payload.source_revision,
                content_sha256=payload_sha256(
                    bar_rows=bar_rows, split_rows=split_rows
                ),
                bar_rows=bar_rows,
                split_rows=split_rows,
            )
            dataset = acquire_point_in_time_dataset(
                security_id=security_id,
                as_of_cutoff=as_of_cutoff,
                currency=payload.currency,
                snapshot=snapshot,
            )
        except QuantContractError as error:
            raise TransportError(
                f"{payload.provider_id} history cannot form a Quant receipt: "
                f"{error}"
            ) from error
        return LiveAcquisition(
            dataset=dataset, bar_rows=bar_rows, split_rows=split_rows
        )


def _rows(
    payload: HistoryPayload, *, start: date, as_of_cutoff: date
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Transport bars mapped to adapter rows, with the whole window enforced.

    Both ends of the requested window are checked, and neither is trimmed. The
    cutoff end is also checked by the Quant adapter; repeating it here is not
    redundancy for its own sake, because the error raised here names the
    transport and the session rather than an anonymous bar.

    The lower bound has no downstream equivalent at all. A bar before the
    requested start is well formed and inside the cutoff, so every contract
    below accepts it; only the request makes it wrong. Trimming it silently
    would produce a receipt for a window the caller never asked for, and the
    hash would then pin the wrong window forever.
    """

    bar_rows: list[dict[str, object]] = []
    split_rows: list[dict[str, object]] = []
    for index, bar in enumerate(payload.bars):
        session = bar.session_date
        if session < start:
            raise TransportError(
                f"{payload.provider_id} bar {index} session {bar.session} is "
                f"before the requested start {start.isoformat()}; the boundary "
                "refuses rather than trimming, because a trimmed window would "
                "be hashed as though it had been requested"
            )
        if session > as_of_cutoff:
            raise TransportError(
                f"{payload.provider_id} bar {index} session "
                f"{bar.session} is after the cutoff {as_of_cutoff.isoformat()}; "
                "the boundary refuses rather than truncating, because it "
                "cannot know which window was meant"
            )
        bar_rows.append(
            {
                "session": bar.session,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
        )
        ratio = Decimal(bar.stock_split)
        if ratio == 0:
            continue
        new_shares, old_shares = ratio.as_integer_ratio()
        split_rows.append(
            {
                "effective_session": bar.session,
                "new_shares": new_shares,
                "old_shares": old_shares,
            }
        )
    return tuple(bar_rows), tuple(split_rows)


class YFinanceHistoryTransport:
    """Bounded live boundary around the unofficial personal-use yfinance package.

    The library module is injected so the mapping and the policy are testable
    with no network. The window is explicit: a start date and a cutoff, never a
    rolling period, because a period selected relative to now is an implicit
    latest selection and cannot be reproduced.

    Adjustment is off in every form the settings expose, and the settings
    object refuses to be constructed otherwise. Unadjusted prices are the whole
    point: an adjusted series silently rewrites history around a split and
    makes a point-in-time receipt a fiction.
    """

    provider_id = YFINANCE_PROVIDER_ID

    def __init__(
        self,
        settings: YFinanceSettings,
        *,
        module: object | None = None,
        caller: BoundedCaller | None = None,
        importer: Callable[[], object] | None = None,
        window_semantics: WindowSemanticsPolicy | None = None,
        allow_test_scope: bool = False,
    ) -> None:
        self.settings = settings
        self._module = module
        self._window_semantics = window_semantics
        self._allow_test_scope = allow_test_scope
        self._importer = importer or _import_yfinance
        self._caller = caller or BoundedCaller(
            policy=YFINANCE_RETRY_POLICY,
            rate_limit=YFINANCE_RATE_LIMIT,
        )

    def fetch_daily_history(
        self, ticker: str, *, start: date, end: date
    ) -> HistoryPayload:
        # A live path is any path that could reach a provider: no injected
        # module means the real library is imported and called.
        authorize_window_semantics(
            self._window_semantics,
            allow_test_scope=self._allow_test_scope,
            live_path=self._module is None,
            library_version=self.settings.library_version,
        )
        module = self._module if self._module is not None else self._importer()
        version = getattr(module, "__version__", None)
        if version != self.settings.library_version:
            raise TransportError(
                f"installed yfinance version {version!r} is not the approved "
                f"{self.settings.library_version!r}"
            )
        if start > end:
            raise TransportError("start must not be after end")

        # yfinance treats ``end`` as exclusive, so the cutoff session is only
        # included when the window ends the day after it.
        window = {
            "start": start.isoformat(),
            "end": (end + timedelta(days=1)).isoformat(),
            "interval": self.settings.interval,
            "auto_adjust": self.settings.auto_adjust,
            "back_adjust": self.settings.back_adjust,
            "prepost": self.settings.prepost,
            "actions": self.settings.actions,
            "repair": self.settings.repair,
            "timeout": self.settings.timeout_seconds,
            "raise_errors": True,
        }

        instrument = module.Ticker(ticker)  # type: ignore[attr-defined]

        def fetch() -> tuple[object, object]:
            try:
                history = instrument.history(**window)
                metadata = instrument.get_history_metadata()
            except Exception as error:  # provider failures are opaque
                raise TransientTransportError(
                    f"could not read Yahoo Finance history: {error}"
                ) from error
            return history, metadata

        history, metadata = self._caller.call(fetch)
        return _yfinance_payload(
            history,
            metadata,
            ticker=ticker,
            settings=self.settings,
            start=start,
            end=end,
        )


def _import_yfinance() -> object:
    try:
        import yfinance as yf
    except ImportError as error:
        raise TransportError(
            "yfinance is not installed; install the market dependency"
        ) from error
    return yf


def _yfinance_payload(
    history: object,
    metadata: object,
    *,
    ticker: str,
    settings: YFinanceSettings,
    start: date,
    end: date,
) -> HistoryPayload:
    index = getattr(history, "index", None)
    if index is None:
        raise TransportError("Yahoo Finance history is missing its index")
    if not isinstance(metadata, dict) or "currency" not in metadata:
        raise TransportError("Yahoo Finance history metadata is incomplete")
    currency = str(metadata["currency"]).upper()

    bars: list[HistoryBar] = []
    for position in range(len(index)):
        row = history.iloc[position]  # type: ignore[attr-defined]
        session = index[position].date()
        try:
            bars.append(
                HistoryBar(
                    session=session,
                    open=_text(row["Open"], field=f"bar {position} open"),
                    high=_text(row["High"], field=f"bar {position} high"),
                    low=_text(row["Low"], field=f"bar {position} low"),
                    close=_text(row["Close"], field=f"bar {position} close"),
                    volume=_whole(row.get("Volume"), field=f"bar {position} volume"),
                    stock_split=_text(
                        row.get("Stock Splits", 0),
                        field=f"bar {position} stock split",
                    ),
                )
            )
        except (KeyError, TypeError) as error:
            raise TransportError(
                f"Yahoo Finance bar {position} is incomplete"
            ) from error

    return HistoryPayload(
        provider_id=YFINANCE_PROVIDER_ID,
        symbol=ticker,
        currency=currency,
        source_revision=_yfinance_revision(
            bars, settings=settings, ticker=ticker, start=start, end=end
        ),
        bars=tuple(bars),
    )


def _scalar(value: object, *, field: str) -> object:
    """One pandas or numpy cell, reduced to a plain Python scalar.

    A real yfinance frame yields ``numpy.float64`` and ``numpy.int64``, not
    ``float`` and ``int``. Both expose ``item()``, which is the documented way
    to get the Python equivalent, so unwrapping here means every rule below is
    written once against plain types instead of once per numpy dtype.

    ``numpy.bool_`` is refused before unwrapping, because it unwraps to ``bool``
    and ``bool`` is an ``int``. A boolean reaching a price or a volume field
    means the frame is not what this code thinks it is.
    """

    if isinstance(value, bool):
        raise TransportError(f"{field} must be numeric, not a boolean")
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, (str, bytes, int, float, Decimal)):
        try:
            unwrapped = item()
        except (TypeError, ValueError) as error:
            raise TransportError(f"{field} is not a numeric scalar") from error
        if isinstance(unwrapped, bool):
            raise TransportError(f"{field} must be numeric, not a boolean")
        return unwrapped
    return value


def _text(value: object, *, field: str) -> str:
    """A yfinance number, carried across as decimal text.

    yfinance returns binary floats. The shortest repr is the closest decimal
    the library itself would print, and it is the only decimal available: the
    precision the vendor actually held is gone before this code runs. That
    limitation belongs to the source, and is stated rather than hidden.

    NaN and infinity are refused here rather than passed on. A missing price is
    the common yfinance defect, and ``Decimal("nan")`` is a legal Decimal that
    would poison every comparison downstream instead of failing at the source.
    """

    value = _scalar(value, field=field)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise TransportError(f"{field} must be a finite number")
        return str(Decimal(str(value)))
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TransportError(f"{field} must be a finite number")
        return str(value)
    if isinstance(value, (int, str)):
        return str(value)
    raise TransportError(f"{field} must be numeric, got {type(value).__name__}")


def _whole(value: object, *, field: str) -> int:
    if value is None:
        raise TransportError(f"{field} is missing; Quant requires volume")
    value = _scalar(value, field=field)
    if isinstance(value, int):
        candidate = value
    elif isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise TransportError(f"{field} must be a finite whole number")
        if not value.is_integer():
            raise TransportError(f"{field} must be a whole number of shares")
        candidate = int(value)
    elif isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise TransportError(f"{field} must be a whole number of shares")
        candidate = int(value)
    else:
        raise TransportError(f"{field} must be a whole number of shares")
    if candidate < 0:
        raise TransportError(f"{field} must not be negative")
    return candidate


def _yfinance_revision(
    bars: Sequence[HistoryBar],
    *,
    settings: YFinanceSettings,
    ticker: str,
    start: date,
    end: date,
) -> str:
    """A revision derived from the payload itself.

    Yahoo publishes no snapshot identifier, so there is nothing authoritative
    to pin. Hashing the returned window is the honest substitute: it is stable
    for the same data and different for different data, which is what makes a
    receipt reproducible. It is not a vendor vintage and does not prove the
    rows were the rows visible on the cutoff date.
    """

    body = json.dumps(
        {
            "library_version": settings.library_version,
            "ticker": ticker,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "bars": [
                [bar.session, bar.open, bar.high, bar.low, bar.close, bar.volume,
                 bar.stock_split]
                for bar in bars
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"yfinance-{settings.library_version}-{hashlib.sha256(body).hexdigest()}"


class MoomooHistoryTransport:
    """Typed placeholder for Moomoo daily history, blocked by design.

    The shape is fixed so the rest of the path is already written against it.
    The behaviour is a stated blocker, because the endpoint has not been
    verified. See ``MOOMOO_HISTORY_BLOCKER``.
    """

    provider_id = MOOMOO_PROVIDER_ID

    def fetch_daily_history(
        self, ticker: str, *, start: date, end: date
    ) -> HistoryPayload:
        raise TransportBlockedError(MOOMOO_HISTORY_BLOCKER)


__all__ = [
    "MOOMOO_HISTORY_BLOCKER",
    "TEST_WINDOW_SEMANTICS_EVIDENCE_SHA256",
    "YFINANCE_END_EXCLUSIVE_EVIDENCE_SHA256",
    "YFINANCE_END_EXCLUSIVE_POLICY_ID",
    "YFINANCE_END_EXCLUSIVE_VERIFIED_ON",
    "yfinance_end_exclusive_policy",
    "TEST_WINDOW_SEMANTICS_POLICY_ID",
    "WINDOW_SEMANTICS_REGISTRY",
    "WindowSemanticsPolicy",
    "YFINANCE_WINDOW_BLOCKER",
    "authorize_window_semantics",
    "test_window_semantics_policy",
    "MOOMOO_PROVIDER_ID",
    "LiveAcquisition",
    "LiveQuantSource",
    "MoomooHistoryTransport",
    "YFINANCE_PROVIDER_ID",
    "YFINANCE_RATE_LIMIT",
    "YFINANCE_RETRY_POLICY",
    "YFinanceHistoryTransport",
]
