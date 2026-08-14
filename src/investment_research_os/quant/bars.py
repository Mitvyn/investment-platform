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
from decimal import Decimal, InvalidOperation
from typing import Iterable, Literal
from uuid import UUID

BarInterval = Literal["1d"]

SUPPORTED_INTERVALS: frozenset[str] = frozenset({"1d"})


class QuantContractError(ValueError):
    """Raised when input data cannot form a valid immutable Quant contract."""


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
        raise QuantContractError(f"{field} must be a decimal, got {type(value).__name__}")

    if not candidate.is_finite():
        raise QuantContractError(f"{field} must be finite, got {candidate}")
    return candidate


def decimal_text(value: Decimal) -> str:
    """Stable textual form for hashing and reporting.

    ``Decimal("1.50")`` and ``Decimal("1.5")`` are numerically equal but have
    different ``str`` output, which would split the content hash. Normalising
    the exponent keeps the hash a function of the value alone.
    """

    normalised = value.normalize()
    if normalised == 0:
        return "0"
    sign, digits, exponent = normalised.as_tuple()
    if isinstance(exponent, int) and exponent > 0:
        normalised = normalised.quantize(Decimal(1))
    return format(normalised, "f")


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
        if not isinstance(self.session, date):
            raise QuantContractError("session must be a date")
        for field in ("open", "high", "low", "close"):
            value = to_decimal(getattr(self, field), field=field)
            object.__setattr__(self, field, value)
            if value <= 0:
                raise QuantContractError(f"{field} must be positive, got {value}")
        if isinstance(self.volume, bool) or not isinstance(self.volume, int):
            raise QuantContractError("volume must be an integer")
        if self.volume < 0:
            raise QuantContractError(f"volume must not be negative, got {self.volume}")
        if self.high < max(self.open, self.close, self.low):
            raise QuantContractError(
                f"high {self.high} is below another price on {self.session.isoformat()}"
            )
        if self.low > min(self.open, self.close, self.high):
            raise QuantContractError(
                f"low {self.low} is above another price on {self.session.isoformat()}"
            )

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
    source: str
    bars: tuple[OhlcvBar, ...]

    def __post_init__(self) -> None:
        try:
            UUID(self.security_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise QuantContractError(
                "security_id must be the canonical security UUID"
            ) from error
        if not isinstance(self.currency, str) or len(self.currency) != 3 or not self.currency.isupper():
            raise QuantContractError("currency must be an upper-case ISO 4217 code")
        if self.interval not in SUPPORTED_INTERVALS:
            raise QuantContractError(f"unsupported interval: {self.interval!r}")
        if not isinstance(self.source, str) or not self.source.strip():
            raise QuantContractError("source must name where the bars came from")

        bars = tuple(self.bars)
        object.__setattr__(self, "bars", bars)
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

    @classmethod
    def from_rows(
        cls,
        *,
        security_id: str,
        currency: str,
        source: str,
        rows: Iterable[dict[str, object]],
        interval: BarInterval = "1d",
    ) -> "BarSeries":
        """Build from provider-shaped rows without importing any provider."""

        bars: list[OhlcvBar] = []
        for index, row in enumerate(rows):
            missing = {"session", "open", "high", "low", "close", "volume"} - set(row)
            if missing:
                raise QuantContractError(
                    f"row {index} is missing {sorted(missing)}"
                )
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
            source=source,
            bars=tuple(bars),
        )

    def to_record(self) -> dict[str, object]:
        return {
            "bars": [bar.to_record() for bar in self.bars],
            "currency": self.currency,
            "interval": self.interval,
            "security_id": self.security_id,
            "source": self.source,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_record())
