"""Provider-neutral immutable OHLCV input contract.

A :class:`BarSeries` is the only way market data enters Quant. It carries no
provider identity beyond an opaque ``source`` label, so a Moomoo adapter, a
CSV import, or a vendor API can all construct one without this module knowing
which produced it.

Prices are :class:`~decimal.Decimal`. Floats are rejected outright: a backtest
whose fills depend on binary rounding is not reproducible, and a content hash
over float text is not stable across languages.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Iterable, Literal
from uuid import UUID

BarInterval = Literal["1d"]
PriceBasis = Literal["unadjusted"]

SUPPORTED_INTERVALS: frozenset[str] = frozenset({"1d"})
PRICE_QUANTUM = Decimal("0.000001")
_QUANT_DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_UP)


class QuantContractError(ValueError):
    """Raised when input data cannot form a valid immutable Quant contract."""


def quant_decimal_context():
    """Return isolated arithmetic context owned by Quant contracts."""

    return localcontext(_QUANT_DECIMAL_CONTEXT)


def canonical_security_id(value: object) -> str:
    """Return canonical UUID text or reject alternate spellings."""

    try:
        parsed = UUID(value)  # type: ignore[arg-type]
    except (AttributeError, TypeError, ValueError) as error:
        raise QuantContractError(
            "security_id must be the canonical security UUID"
        ) from error
    canonical = str(parsed)
    if value != canonical:
        raise QuantContractError("security_id must be the canonical security UUID")
    return canonical


def canonical_sha256(payload: object) -> str:
    """Content hash over canonical JSON.

    ``ensure_ascii=False`` matches the platform-wide canonical form, so a
    non-ASCII field hashes identically in Python, TypeScript, and SQL.
    """

    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def to_decimal(value: object, *, field: str) -> Decimal:
    """Coerce to Decimal, rejecting floats and non-finite values."""

    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, bool):
        raise QuantContractError(f"{field} must be a decimal, not a boolean")
    elif isinstance(value, int):
        candidate = Decimal(value)
    elif isinstance(value, str):
        try:
            candidate = Decimal(value)
        except InvalidOperation as error:
            raise QuantContractError(f"{field} is not a decimal: {value!r}") from error
    elif isinstance(value, float):
        raise QuantContractError(
            f"{field} must be a Decimal or decimal string, not a float; "
            "binary floats make fills irreproducible"
        )
    else:
        raise QuantContractError(
            f"{field} must be a decimal, got {type(value).__name__}"
        )

    if not candidate.is_finite():
        raise QuantContractError(f"{field} must be finite, got {candidate}")
    return candidate


def decimal_text(value: Decimal) -> str:
    """Stable textual form for hashing and reporting.

    ``Decimal("1.50")`` and ``Decimal("1.5")`` are numerically equal but have
    different ``str`` output, which would split the content hash. Normalising
    the exponent keeps the hash a function of the value alone.
    """

    if value == 0:
        return "0"
    sign, raw_digits, raw_exponent = value.as_tuple()
    if not isinstance(raw_exponent, int):
        raise QuantContractError("decimal value must be finite")
    digits = list(raw_digits)
    exponent = raw_exponent
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = "".join(str(digit) for digit in digits)
    decimal_position = len(coefficient) + exponent
    if decimal_position <= 0:
        body = f"0.{('0' * -decimal_position)}{coefficient}"
    elif decimal_position >= len(coefficient):
        body = f"{coefficient}{'0' * (decimal_position - len(coefficient))}"
    else:
        body = f"{coefficient[:decimal_position]}.{coefficient[decimal_position:]}"
    return f"-{body}" if sign else body


@dataclass(frozen=True, slots=True)
class OhlcvBar:
    """One immutable session of open/high/low/close/volume."""

    session: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        _check_bar(self, coerce=True)

    def to_record(self) -> dict[str, object]:
        return {
            "close": decimal_text(self.close),
            "high": decimal_text(self.high),
            "low": decimal_text(self.low),
            "open": decimal_text(self.open),
            "session": self.session.isoformat(),
            "volume": self.volume,
        }


@dataclass(frozen=True, slots=True)
class BarSeries:
    """An immutable, strictly ordered bar history for one canonical security.

    ``security_id`` is the canonical identifier shared with other bounded
    contexts. It is the only cross-domain field; nothing else here is
    meaningful outside Quant.
    """

    security_id: str
    currency: str
    interval: BarInterval
    price_basis: PriceBasis
    source: str
    bars: tuple[OhlcvBar, ...]

    def __post_init__(self) -> None:
        _check_series(self, coerce=True)

    @classmethod
    def from_rows(
        cls,
        *,
        security_id: str,
        currency: str,
        price_basis: PriceBasis,
        source: str,
        rows: Iterable[dict[str, object]],
        interval: BarInterval = "1d",
    ) -> "BarSeries":
        """Build from provider-shaped rows without importing any provider."""

        bars: list[OhlcvBar] = []
        for index, row in enumerate(rows):
            missing = {"session", "open", "high", "low", "close", "volume"} - set(row)
            if missing:
                raise QuantContractError(f"row {index} is missing {sorted(missing)}")
            session = row["session"]
            if isinstance(session, str):
                session = date.fromisoformat(session)
            bars.append(
                OhlcvBar(
                    session=session,  # type: ignore[arg-type]
                    open=row["open"],  # type: ignore[arg-type]
                    high=row["high"],  # type: ignore[arg-type]
                    low=row["low"],  # type: ignore[arg-type]
                    close=row["close"],  # type: ignore[arg-type]
                    volume=row["volume"],  # type: ignore[arg-type]
                )
            )
        return cls(
            security_id=security_id,
            currency=currency,
            interval=interval,
            price_basis=price_basis,
            source=source,
            bars=tuple(bars),
        )

    def to_record(self) -> dict[str, object]:
        return {
            "bars": [bar.to_record() for bar in self.bars],
            "currency": self.currency,
            "interval": self.interval,
            "price_basis": self.price_basis,
            "security_id": self.security_id,
            "source": self.source,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_record())


def _check_bar(bar: "OhlcvBar", *, coerce: bool) -> None:
    """Every ``OhlcvBar`` invariant, shared by construction and revalidation.

    ``coerce`` is the whole difference between the two callers. At construction
    a caller may hand over ``"100"`` or ``100`` and have it stored as a
    ``Decimal``. At runtime nothing is repaired: a tampered object must be
    rejected as it stands, because normalising it would launder a mutation back
    into a valid-looking contract.
    """

    if type(bar.session) is not date:
        raise QuantContractError("session must be a date")
    for field in ("open", "high", "low", "close"):
        raw = getattr(bar, field)
        if coerce:
            value = to_decimal(raw, field=field)
            object.__setattr__(bar, field, value)
        else:
            if type(raw) is not Decimal:
                raise QuantContractError(
                    f"{field} must be a stored Decimal, got {type(raw).__name__}"
                )
            if not raw.is_finite():
                raise QuantContractError(f"{field} must be finite, got {raw}")
            value = raw
        if value < PRICE_QUANTUM:
            raise QuantContractError(
                f"{field} must be at least price quantum {PRICE_QUANTUM}, got {value}"
            )
    if isinstance(bar.volume, bool) or not isinstance(bar.volume, int):
        raise QuantContractError("volume must be an integer")
    if bar.volume < 0:
        raise QuantContractError(f"volume must not be negative, got {bar.volume}")
    if bar.high < max(bar.open, bar.close, bar.low):
        raise QuantContractError(
            f"high {bar.high} is below another price on {bar.session.isoformat()}"
        )
    if bar.low > min(bar.open, bar.close, bar.high):
        raise QuantContractError(
            f"low {bar.low} is above another price on {bar.session.isoformat()}"
        )


def _check_series(series: "BarSeries", *, coerce: bool) -> None:
    """Every ``BarSeries`` invariant, including each bar it holds."""

    canonical_security_id(series.security_id)
    if (
        not isinstance(series.currency, str)
        or len(series.currency) != 3
        or not series.currency.isupper()
    ):
        raise QuantContractError("currency must be an upper-case ISO 4217 code")
    if series.interval not in SUPPORTED_INTERVALS:
        raise QuantContractError(f"unsupported interval: {series.interval!r}")
    if series.price_basis != "unadjusted":
        raise QuantContractError(
            "price_basis must be unadjusted before corporate actions are applied"
        )
    if not isinstance(series.source, str) or not series.source.strip():
        raise QuantContractError("source must name where the bars came from")

    if coerce:
        bars = tuple(series.bars)
        object.__setattr__(series, "bars", bars)
    else:
        # A list here is not a shape to fix up; it is evidence the object was
        # written to after construction.
        if type(series.bars) is not tuple:
            raise QuantContractError(
                f"bars must be a stored tuple, got {type(series.bars).__name__}"
            )
        bars = series.bars
        for bar in bars:
            if not isinstance(bar, OhlcvBar):
                raise QuantContractError(
                    f"bars must hold OhlcvBar, got {type(bar).__name__}"
                )
            _check_bar(bar, coerce=False)
    if len(bars) < 2:
        raise QuantContractError(
            "a bar series needs at least two sessions to evaluate a decision"
        )
    for earlier, later in zip(bars, bars[1:]):
        if later.session <= earlier.session:
            raise QuantContractError(
                "sessions must be strictly increasing; "
                f"{later.session.isoformat()} does not follow "
                f"{earlier.session.isoformat()}"
            )


def revalidate_bar_series(series: object) -> "BarSeries":
    """Re-check a series and every bar in it, returning it unchanged.

    Raises ``QuantContractError`` and nothing else. No coercion, no repair, no
    I/O.
    """

    if not isinstance(series, BarSeries):
        raise QuantContractError(
            f"expected a BarSeries, got {type(series).__name__}"
        )
    _check_series(series, coerce=False)
    return series
