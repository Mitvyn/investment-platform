"""Offline acquisition boundary between a market-data source and Quant.

Quant core accepts exactly one input: a validated ``PointInTimeDataset``. This
module is where an outside payload becomes one. It sits **outside** the Quant
package on purpose, and the dependency runs one way only: the adapter imports
Quant contracts, and Quant imports nothing from here. A future Moomoo, CSV, or
vendor adapter fetches bytes and hands them to this function; none of them
becomes a Quant dependency by doing so.

Nothing in this module performs I/O, opens a network connection, reads a clock,
or knows a provider exists. A ``SourceSnapshot`` is data the caller already holds. That
keeps the acquisition rules testable offline and keeps the fetching concern,
which needs credentials and a network, in a separate layer that can be swapped
without touching these rules.

**What the content hash does and does not prove.** ``payload_sha256`` is
computed over the rows as sent, and the adapter refuses a snapshot whose
declared hash does not match. That detects an altered or replayed payload
between declaration and use, which is a real integrity property. It does
**not** prove the vendor held this data on the cutoff date, that the revision
names a real vendor snapshot, or that the rows are free of restatement. Those
remain declarations, exactly as in ``quant.dataset``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Sequence

from investment_research_os.quant.bars import (
    BarSeries,
    OhlcvBar,
    QuantContractError,
    canonical_security_id,
    canonical_sha256,
    quant_decimal_context,
)
from investment_research_os.quant.corporate_actions import (
    CorporateActionSet,
    StockSplit,
)
from investment_research_os.quant.dataset import PointInTimeDataset

ADAPTER_VERSION = "quant-source-adapter-1"

#: Required bar-row keys. ``security_id`` is optional; when present it must
#: agree with the requested identity rather than establish it.
_BAR_FIELDS = frozenset(
    {"session", "open", "high", "low", "close", "volume"}
)
_OPTIONAL_ROW_FIELDS = frozenset({"security_id"})
_SPLIT_FIELDS = frozenset({"effective_session", "new_shares", "old_shares"})

_SHA256_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")

#: Revision strings that name a moving target instead of a fixed snapshot. A
#: receipt pinned to one of these could never be reproduced, because the thing
#: it names is different tomorrow.
_MOVING_REVISIONS = frozenset(
    {"latest", "current", "head", "newest", "now", "live", "today"}
)


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QuantContractError(f"{field} must be a non-empty string")
    return value


def _currency(value: object) -> str:
    """ISO 4217 alphabetic code, stated by the caller.

    There is no default. A source payload carries prices without saying what
    they are denominated in, and guessing USD would make a Hong Kong or London
    series silently wrong in a field nothing downstream ever checks.
    """

    if (
        not isinstance(value, str)
        or len(value) != 3
        or not value.isalpha()
        or not value.isupper()
    ):
        raise QuantContractError(
            "currency must be an upper-case three-letter ISO 4217 code, "
            "stated explicitly; there is no default"
        )
    return value


def _sha256_text(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or not set(value) <= _HEX_DIGITS
    ):
        raise QuantContractError(
            f"{field} must be a lowercase 64-character SHA-256 digest"
        )
    return value


def _rows(value: object, *, field: str) -> tuple[Mapping[str, object], ...]:
    """Check the shape of a row sequence without copying it."""

    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise QuantContractError(f"{field} must be a sequence of rows")
    rows = tuple(value)
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise QuantContractError(
                f"{field}[{index}] must be a mapping, got {type(row).__name__}"
            )
    return rows


def _frozen_rows(
    value: object, *, field: str
) -> tuple[Mapping[str, object], ...]:
    """Rows copied into read-only mappings the caller cannot reach.

    A snapshot holding the caller's own ``dict`` objects is not immutable in any
    useful sense: the caller keeps a reference and can rewrite a price after the
    content hash was declared over it. Copying defeats that, and the read-only
    view defeats writing through the snapshot itself. Values are checked here
    too, so a row cannot hold something that has no stable hashable form.
    """

    rows = _rows(value, field=field)
    frozen: list[Mapping[str, object]] = []
    for index, row in enumerate(rows):
        entry: dict[str, object] = {}
        for key in row:
            if not isinstance(key, str):
                raise QuantContractError(
                    f"{field}[{index}] keys must be strings, got "
                    f"{type(key).__name__}"
                )
            entry[key] = _hashable_value(row[key], field=f"{field}[{index}].{key}")
        frozen.append(MappingProxyType(entry))
    return tuple(frozen)


def _hashable_value(value: object, *, field: str) -> object:
    """One source field, restricted to values with a stable canonical form."""

    if value is None or isinstance(value, (bool, str, int, Decimal, date)):
        return value
    raise QuantContractError(
        f"{field} is not hashable source data: {type(value).__name__}"
    )


def _canonical_rows(
    rows: tuple[Mapping[str, object], ...]
) -> list[dict[str, object]]:
    """Rows reduced to JSON-safe scalars, in key order, for hashing.

    Values are hashed as the source sent them. ``"100"`` and ``"100.0"`` are
    the same number and a different declaration, and the payload hash is about
    the declaration.
    """

    canonical: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        entry: dict[str, object] = {}
        for key in sorted(row, key=str):
            value = _hashable_value(row[key], field=f"row {index} field {key!r}")
            if isinstance(value, Decimal):
                entry[str(key)] = str(value)
            elif isinstance(value, date) and not isinstance(value, bool):
                entry[str(key)] = value.isoformat()
            else:
                entry[str(key)] = value
        canonical.append(entry)
    return canonical


def payload_sha256(
    *,
    bar_rows: Sequence[Mapping[str, object]],
    split_rows: Sequence[Mapping[str, object]],
) -> str:
    """Content hash of one source payload, before any interpretation.

    Deterministic across key order and independent of the ambient Decimal
    context. A caller declares this value alongside the payload; the adapter
    recomputes it and refuses a mismatch.
    """

    with quant_decimal_context():
        return canonical_sha256(
            {
                "adapter_version": ADAPTER_VERSION,
                "bar_rows": _canonical_rows(_rows(bar_rows, field="bar_rows")),
                "split_rows": _canonical_rows(
                    _rows(split_rows, field="split_rows")
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """One immutable, already-retrieved payload from one named source revision.

    This carries no provider identity beyond opaque labels, so a broker API, a
    CSV export, and a fixture all produce the same shape. It holds no
    connection, credential, or cursor.
    """

    source_id: str
    source_revision: str
    content_sha256: str
    bar_rows: tuple[Mapping[str, object], ...]
    split_rows: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "bar_rows", _frozen_rows(self.bar_rows, field="bar_rows")
        )
        object.__setattr__(
            self, "split_rows", _frozen_rows(self.split_rows, field="split_rows")
        )
        _check_declarations(self)

    def to_record(self) -> dict[str, object]:
        return {
            "adapter_version": ADAPTER_VERSION,
            "bar_row_count": len(self.bar_rows),
            "content_sha256": self.content_sha256,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "split_row_count": len(self.split_rows),
        }


def _check_declarations(snapshot: "SourceSnapshot") -> None:
    """The declaration rules, shared by construction and revalidation."""

    _text(snapshot.source_id, field="source_id")
    revision = _text(snapshot.source_revision, field="source_revision")
    if revision.strip().lower() in _MOVING_REVISIONS:
        raise QuantContractError(
            f"source_revision {revision!r} names a moving target, not a "
            "revision; an implicit latest selection cannot be reproduced"
        )
    _sha256_text(snapshot.content_sha256, field="content_sha256")


def revalidate_source_snapshot(
    snapshot: object, *, as_of_cutoff: date | None = None
) -> "SourceSnapshot":
    """Re-check a snapshot at the acquisition boundary and return it unchanged.

    A frozen dataclass is only as immutable as ``object.__setattr__`` allows, so
    a snapshot arriving here may bear none of the guarantees its type implies.
    Everything is rechecked: the declarations, the row shape and value types,
    and the payload against its own declared hash. Nothing is repaired.

    ``as_of_cutoff`` is optional because a snapshot has no cutoff of its own —
    the cutoff belongs to the acquisition request. When one is supplied, rows
    and splits dated after it are refused here as well, so a caller can check a
    payload against an intended cutoff without building a receipt.

    Raises ``QuantContractError`` and nothing else.
    """

    if not isinstance(snapshot, SourceSnapshot):
        raise QuantContractError(
            f"expected a SourceSnapshot, got {type(snapshot).__name__}"
        )
    _check_declarations(snapshot)
    bar_rows = _rows(snapshot.bar_rows, field="bar_rows")
    split_rows = _rows(snapshot.split_rows, field="split_rows")
    if not isinstance(snapshot.bar_rows, tuple) or not isinstance(
        snapshot.split_rows, tuple
    ):
        raise QuantContractError("rows must be stored as tuples")
    for label, rows, required in (
        ("bar", bar_rows, _BAR_FIELDS),
        ("split", split_rows, _SPLIT_FIELDS),
    ):
        for index, row in enumerate(rows):
            _check_row_keys(row, index=index, required=required, label=label)
            for key in row:
                _hashable_value(row[key], field=f"{label} row {index} {key}")

    recomputed = payload_sha256(bar_rows=bar_rows, split_rows=split_rows)
    if recomputed != snapshot.content_sha256:
        raise QuantContractError(
            "source payload does not match its declared content hash; the "
            f"payload hashes to {recomputed}, the snapshot declares "
            f"{snapshot.content_sha256}"
        )

    if as_of_cutoff is not None:
        if type(as_of_cutoff) is not date:
            raise QuantContractError("as_of_cutoff must be a date")
        for label, rows, key in (
            ("bar", bar_rows, "session"),
            ("split", split_rows, "effective_session"),
        ):
            for index, row in enumerate(rows):
                session = _session(row[key], field=f"{label} row {index} {key}")
                if session > as_of_cutoff:
                    raise QuantContractError(
                        f"{label} row {index} {key} {session.isoformat()} is after "
                        f"the cutoff {as_of_cutoff.isoformat()}; the adapter "
                        "refuses rather than truncating, because it cannot know "
                        "which window was meant"
                    )
    return snapshot


def _session(value: object, *, field: str) -> date:
    """Session date from ISO text or an exact ``date``.

    A ``datetime`` is refused even though it is a ``date`` subclass: a session
    is a trading day, and a wall-clock instant carries a timezone question this
    contract has no answer for.
    """

    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise QuantContractError(
            f"{field} must be an ISO date string or a date, got "
            f"{type(value).__name__}"
        )
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise QuantContractError(f"{field} is not an ISO date: {value!r}") from error


def _numeric_text(value: object, *, field: str) -> str | int | Decimal:
    """Reject floats before they reach a price field.

    ``OhlcvBar`` rejects floats too. Doing it here as well means the error names
    the offending source row rather than an anonymous bar.
    """

    if isinstance(value, float):
        raise QuantContractError(
            f"{field} is a float; binary floats make fills irreproducible, so "
            "a source must send decimal text"
        )
    if isinstance(value, bool):
        raise QuantContractError(f"{field} must be a decimal, not a boolean")
    if isinstance(value, (str, int, Decimal)):
        return value
    raise QuantContractError(
        f"{field} must be decimal text, got {type(value).__name__}"
    )


def _volume(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise QuantContractError(
            f"{field} must be a whole number of shares, got {type(value).__name__}"
        )
    return value


def _check_row_keys(
    row: Mapping[str, object], *, index: int, required: frozenset[str], label: str
) -> None:
    keys = set(row)
    missing = required - keys
    if missing:
        raise QuantContractError(
            f"{label} row {index} is missing {sorted(missing)}"
        )
    unknown = keys - required - _OPTIONAL_ROW_FIELDS
    if unknown:
        raise QuantContractError(
            f"{label} row {index} carries unsupported fields {sorted(unknown)}; "
            "an unrecognised column may be an adjusted price or another basis"
        )


def _declared_identity(
    row: Mapping[str, object], *, security_id: str, index: int, label: str
) -> None:
    if "security_id" not in row:
        return
    declared = row["security_id"]
    if declared != security_id:
        raise QuantContractError(
            f"{label} row {index} declares security {declared!r}, not the "
            f"requested {security_id!r}"
        )


def _build_series(
    *,
    security_id: str,
    currency: str,
    source_id: str,
    rows: tuple[Mapping[str, object], ...],
    as_of_cutoff: date,
) -> BarSeries:
    bars: list[OhlcvBar] = []
    for index, row in enumerate(rows):
        _check_row_keys(row, index=index, required=_BAR_FIELDS, label="bar")
        _declared_identity(row, security_id=security_id, index=index, label="bar")
        session = _session(row["session"], field=f"bar row {index} session")
        if session > as_of_cutoff:
            raise QuantContractError(
                f"bar row {index} session {session.isoformat()} is after the "
                f"cutoff {as_of_cutoff.isoformat()}; the adapter refuses rather "
                "than truncating, because it cannot know which window was meant"
            )
        bars.append(
            OhlcvBar(
                session=session,
                open=_numeric_text(row["open"], field=f"bar row {index} open"),
                high=_numeric_text(row["high"], field=f"bar row {index} high"),
                low=_numeric_text(row["low"], field=f"bar row {index} low"),
                close=_numeric_text(row["close"], field=f"bar row {index} close"),
                volume=_volume(row["volume"], field=f"bar row {index} volume"),
            )
        )
    # Order is checked by BarSeries, which rejects a duplicate or out-of-order
    # session. Sorting here would hide that the source sent them that way.
    return BarSeries(
        security_id=security_id,
        currency=currency,
        interval="1d",
        price_basis="unadjusted",
        source=source_id,
        bars=tuple(bars),
    )


def _build_actions(
    *,
    security_id: str,
    source_id: str,
    rows: tuple[Mapping[str, object], ...],
    as_of_cutoff: date,
    covered_sessions: frozenset[date],
) -> CorporateActionSet:
    splits: list[StockSplit] = []
    for index, row in enumerate(rows):
        _check_row_keys(row, index=index, required=_SPLIT_FIELDS, label="split")
        _declared_identity(row, security_id=security_id, index=index, label="split")
        session = _session(
            row["effective_session"], field=f"split row {index} effective_session"
        )
        if session > as_of_cutoff:
            raise QuantContractError(
                f"split row {index} effective {session.isoformat()} is after the "
                f"cutoff {as_of_cutoff.isoformat()}"
            )
        # The engine transitions into bars[1:] only, and refuses an action
        # dated anywhere else. Catching it here names the offending source row
        # instead of aborting a backtest much later for a reason that has
        # nothing to do with the strategy.
        if session not in covered_sessions:
            raise QuantContractError(
                f"split row {index} effective {session.isoformat()} is not a "
                "covered transition session; an action must fall on a bar the "
                "engine trades into, which excludes the first bar and any "
                "session the series does not contain"
            )
        for field in ("new_shares", "old_shares"):
            value = row[field]
            if isinstance(value, bool) or not isinstance(value, int):
                raise QuantContractError(
                    f"split row {index} {field} must be a whole number, got "
                    f"{type(value).__name__}"
                )
        splits.append(
            StockSplit(
                effective_session=session,
                new_shares=row["new_shares"],  # type: ignore[arg-type]
                old_shares=row["old_shares"],  # type: ignore[arg-type]
            )
        )
    return CorporateActionSet(
        security_id=security_id,
        source=source_id,
        actions=tuple(splits),
    )


def acquire_point_in_time_dataset(
    *,
    security_id: str,
    as_of_cutoff: date,
    currency: str,
    snapshot: SourceSnapshot,
) -> PointInTimeDataset:
    """Turn one declared source payload into one validated Quant receipt.

    Every input is explicit. Nothing is fetched, defaulted from a clock, or
    inferred from the rows: the identity and the cutoff are what the caller
    asked for, and a payload that disagrees is refused rather than reconciled.

    Fails closed on a post-cutoff bar or split, a missing or moving source
    revision, a malformed or mismatched content hash, a float in a numeric
    field, a duplicate or out-of-order session, a row declaring another
    security, and an unrecognised column.
    """

    canonical_id = canonical_security_id(security_id)
    if type(as_of_cutoff) is not date:
        raise QuantContractError("as_of_cutoff must be a date")
    _currency(currency)

    # Integrity before interpretation. If the snapshot is not the one it claims
    # to be, or the payload is not the one whose hash was declared, nothing
    # downstream is worth computing.
    revalidate_source_snapshot(snapshot, as_of_cutoff=as_of_cutoff)

    with quant_decimal_context():
        series = _build_series(
            security_id=canonical_id,
            currency=currency,
            source_id=snapshot.source_id,
            rows=snapshot.bar_rows,
            as_of_cutoff=as_of_cutoff,
        )
        actions = _build_actions(
            security_id=canonical_id,
            source_id=snapshot.source_id,
            rows=snapshot.split_rows,
            as_of_cutoff=as_of_cutoff,
            covered_sessions=frozenset(bar.session for bar in series.bars[1:]),
        )
        return PointInTimeDataset(
            series=series,
            corporate_actions=actions,
            as_of_cutoff=as_of_cutoff,
            source_id=snapshot.source_id,
            source_revision=snapshot.source_revision,
            source_content_sha256=snapshot.content_sha256,
            coverage_scope="single_security",
        )
