"""Deterministic Decimal statistics for Quant validation.

No floats, no random number generator, and no distribution function. Every
value is computed inside the package's isolated Decimal context so a caller's
global context cannot change a verdict.

Significance is decided against a frozen table of one-sided Student's t
critical values rather than a computed p-value. Converting a t-statistic to a
p-value needs an incomplete beta or error function, and an approximate
implementation would emit an authoritative-looking number that is wrong. A
table is honest about being a table, is exact, and cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping, Sequence

from investment_research_os.quant.bars import (
    QuantContractError,
    decimal_text,
    quant_decimal_context,
    to_decimal,
)

RATIO_QUANTUM = Decimal("0.000001")

#: Degrees-of-freedom buckets, ascending. A lookup rounds *down* to the
#: nearest bucket, which demands a larger statistic than strictly necessary.
DEGREES_OF_FREEDOM_BUCKETS: tuple[int, ...] = (10, 20, 30, 60, 120, 250, 500, 1000)

#: Tabulated one-sided alpha levels, ascending by strictness.
ALPHA_LABELS: tuple[str, ...] = ("0.05", "0.01", "0.005", "0.001")

#: One-sided Student's t critical values, keyed by (df bucket, alpha label).
CRITICAL_VALUES: Mapping[tuple[int, str], Decimal] = {
    (10, "0.05"): Decimal("1.812"),
    (10, "0.01"): Decimal("2.764"),
    (10, "0.005"): Decimal("3.169"),
    (10, "0.001"): Decimal("4.144"),
    (20, "0.05"): Decimal("1.725"),
    (20, "0.01"): Decimal("2.528"),
    (20, "0.005"): Decimal("2.845"),
    (20, "0.001"): Decimal("3.552"),
    (30, "0.05"): Decimal("1.697"),
    (30, "0.01"): Decimal("2.457"),
    (30, "0.005"): Decimal("2.750"),
    (30, "0.001"): Decimal("3.385"),
    (60, "0.05"): Decimal("1.671"),
    (60, "0.01"): Decimal("2.390"),
    (60, "0.005"): Decimal("2.660"),
    (60, "0.001"): Decimal("3.232"),
    (120, "0.05"): Decimal("1.658"),
    (120, "0.01"): Decimal("2.358"),
    (120, "0.005"): Decimal("2.617"),
    (120, "0.001"): Decimal("3.160"),
    (250, "0.05"): Decimal("1.651"),
    (250, "0.01"): Decimal("2.341"),
    (250, "0.005"): Decimal("2.596"),
    (250, "0.001"): Decimal("3.123"),
    (500, "0.05"): Decimal("1.648"),
    (500, "0.01"): Decimal("2.334"),
    (500, "0.005"): Decimal("2.586"),
    (500, "0.001"): Decimal("3.107"),
    (1000, "0.05"): Decimal("1.646"),
    (1000, "0.01"): Decimal("2.330"),
    (1000, "0.005"): Decimal("2.581"),
    (1000, "0.001"): Decimal("3.098"),
}


def resolve_degrees_of_freedom_bucket(degrees_of_freedom: int) -> int | None:
    """Largest tabulated bucket at or below ``degrees_of_freedom``."""

    if isinstance(degrees_of_freedom, bool) or not isinstance(degrees_of_freedom, int):
        raise QuantContractError("degrees_of_freedom must be an integer")
    candidates = [
        bucket for bucket in DEGREES_OF_FREEDOM_BUCKETS if bucket <= degrees_of_freedom
    ]
    return max(candidates) if candidates else None


def resolve_alpha_label(alpha: Decimal) -> str | None:
    """Largest tabulated alpha at or below ``alpha``.

    Rounding down makes the test stricter than requested, never looser. An
    alpha below the smallest tabulated level has no answer, and the caller
    must treat that as insufficient rather than as a pass.
    """

    value = to_decimal(alpha, field="alpha")
    if value <= 0:
        raise QuantContractError(f"alpha must be positive, got {value}")
    candidates = [label for label in ALPHA_LABELS if Decimal(label) <= value]
    if not candidates:
        return None
    return max(candidates, key=Decimal)


def critical_value(*, degrees_of_freedom: int, alpha: Decimal) -> Decimal | None:
    """One-sided critical value, or None when the lookup leaves the table."""

    bucket = resolve_degrees_of_freedom_bucket(degrees_of_freedom)
    if bucket is None:
        return None
    label = resolve_alpha_label(alpha)
    if label is None:
        return None
    return CRITICAL_VALUES[(bucket, label)]


def simple_returns(equity: Sequence[Decimal]) -> tuple[Decimal, ...]:
    """Period-over-period simple returns.

    Simple rather than log returns: Decimal has no natural logarithm, and
    implementing one to the working precision purely to satisfy a convention
    would trade an exact number for an approximate one.
    """

    values = [to_decimal(point, field="equity") for point in equity]
    with quant_decimal_context():
        returns: list[Decimal] = []
        for earlier, later in zip(values, values[1:]):
            if earlier == 0:
                raise QuantContractError(
                    "equity of zero has no defined return; the series is unusable"
                )
            returns.append((later - earlier) / earlier)
        return tuple(returns)


@dataclass(frozen=True, slots=True)
class ReturnStatistics:
    """Summary of one return series. Dispersion is None when unmeasurable."""

    count: int
    degrees_of_freedom: int
    annualisation_periods: int
    mean: Decimal
    stdev: Decimal | None
    sharpe_ratio: Decimal | None
    t_statistic: Decimal | None

    def to_record(self) -> dict[str, object]:
        return {
            "annualisation_periods": self.annualisation_periods,
            "count": self.count,
            "degrees_of_freedom": self.degrees_of_freedom,
            "mean": decimal_text(self.mean),
            "sharpe_ratio": (
                None if self.sharpe_ratio is None else decimal_text(self.sharpe_ratio)
            ),
            "stdev": None if self.stdev is None else decimal_text(self.stdev),
            "t_statistic": (
                None if self.t_statistic is None else decimal_text(self.t_statistic)
            ),
        }


def summarise_returns(
    returns: Sequence[Decimal],
    *,
    annualisation_periods: int,
) -> ReturnStatistics:
    """Mean, sample dispersion, Sharpe, and t-statistic for a return series.

    The sample standard deviation uses the ``n - 1`` denominator, so a series
    of one observation has no dispersion at all. That case returns None rather
    than zero: a zero would read as a measurement, and a caller comparing it
    against a threshold would silently treat "unmeasurable" as "no risk".
    """

    if (
        isinstance(annualisation_periods, bool)
        or not isinstance(annualisation_periods, int)
        or annualisation_periods < 1
    ):
        raise QuantContractError("annualisation_periods must be a positive integer")
    values = [to_decimal(value, field="return") for value in returns]
    if not values:
        raise QuantContractError("a return series must have at least one observation")

    count = len(values)
    with quant_decimal_context():
        mean = sum(values, Decimal(0)) / Decimal(count)
        if count < 2:
            return ReturnStatistics(
                count=count,
                degrees_of_freedom=count - 1,
                annualisation_periods=annualisation_periods,
                mean=mean.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP),
                stdev=None,
                sharpe_ratio=None,
                t_statistic=None,
            )

        squared = sum(((value - mean) ** 2 for value in values), Decimal(0))
        variance = squared / Decimal(count - 1)
        stdev = variance.sqrt()
        if stdev == 0:
            sharpe: Decimal | None = None
            t_statistic: Decimal | None = None
        else:
            sharpe = (
                mean / stdev * Decimal(annualisation_periods).sqrt()
            ).quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP)
            t_statistic = (
                mean / (stdev / Decimal(count).sqrt())
            ).quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP)

        return ReturnStatistics(
            count=count,
            degrees_of_freedom=count - 1,
            annualisation_periods=annualisation_periods,
            mean=mean.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP),
            stdev=stdev.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP),
            sharpe_ratio=sharpe,
            t_statistic=t_statistic,
        )
