"""Immutable point-in-time dataset contract for single-security Quant work.

A backtest is only as trustworthy as the claim that its inputs were knowable
at the time. This module makes that claim explicit and hashable instead of
implicit: bars, corporate actions, an as-of cutoff, and an opaque declaration
of which source revision produced them are frozen together into one record
whose ``content_sha256`` changes if any of them changes.

Nothing here infers anything. The cutoff, the source identity, the source
revision, the source content hash, the security identity, and the corporate
actions are all supplied by the caller. A future adapter may construct this
contract from a provider; this module never learns that the provider exists,
performs no I/O, reads no clock, and holds no registry state.

**Coverage limit, stated in code because it is easy to forget downstream.**
``coverage_scope`` is ``"single_security"``. That establishes exactly one
thing: these bars and actions are declared knowable as of this cutoff for this
one canonical ``security_id``. It does **not** establish historical universe
membership, delisting coverage, or the absence of survivorship bias. A
strategy validated across a set of these datasets has been tested on the
securities someone chose to assemble, which is not the same as the securities
that existed at the time. Any universe-level claim needs a universe-level
contract that does not exist yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from investment_research_os.quant.bars import (
    BarSeries,
    QuantContractError,
    canonical_sha256,
    quant_decimal_context,
    revalidate_bar_series,
)
from investment_research_os.quant.corporate_actions import (
    CorporateActionSet,
    revalidate_corporate_action_set,
)

DATASET_VERSION = "quant-dataset-1"

CoverageScope = Literal["single_security"]

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QuantContractError(f"{field} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class PointInTimeDataset:
    """One security's bars and corporate actions, frozen as of a stated cutoff.

    Every field is required. A default would let a caller obtain a dataset
    whose provenance nobody declared, and an undeclared provenance is exactly
    the thing this contract exists to prevent.
    """

    series: BarSeries
    corporate_actions: CorporateActionSet
    as_of_cutoff: date
    source_id: str
    source_revision: str
    source_content_sha256: str
    coverage_scope: CoverageScope

    def __post_init__(self) -> None:
        _check_invariants(self)

    @property
    def security_id(self) -> str:
        """The canonical identity, taken from the series and nowhere else."""

        return self.series.security_id

    def to_record(self) -> dict[str, object]:
        """Canonical record pinning every declared input and both child hashes."""

        with quant_decimal_context():
            return {
                "as_of_cutoff": self.as_of_cutoff.isoformat(),
                "corporate_actions": self.corporate_actions.to_record(),
                "corporate_actions_sha256": self.corporate_actions.content_sha256,
                "coverage_scope": self.coverage_scope,
                "dataset_version": DATASET_VERSION,
                "security_id": self.security_id,
                "series": self.series.to_record(),
                "series_sha256": self.series.content_sha256,
                "source_content_sha256": self.source_content_sha256,
                "source_id": self.source_id,
                "source_revision": self.source_revision,
            }

    @property
    def content_sha256(self) -> str:
        with quant_decimal_context():
            return canonical_sha256(self.to_record())


def _check_invariants(dataset: PointInTimeDataset) -> None:
    """Every receipt invariant, in one place.

    Called at construction and again at each execution boundary. A frozen
    dataclass is not a protection boundary — ``object.__setattr__`` walks
    straight through it — so the rules live in a function both callers share.
    Two divergent copies would be worse than no second check at all.
    """

    if not isinstance(dataset.series, BarSeries):
        raise QuantContractError("series must be a BarSeries")
    if not isinstance(dataset.corporate_actions, CorporateActionSet):
        raise QuantContractError(
            "corporate_actions must be a CorporateActionSet"
        )

    # Guarded here as well as in BarSeries. A future widened interval or
    # price basis must not silently enter a daily unadjusted dataset.
    if dataset.series.interval != "1d":
        raise QuantContractError(
            f"a point-in-time dataset holds daily bars, got {dataset.series.interval!r}"
        )
    if dataset.series.price_basis != "unadjusted":
        raise QuantContractError(
            "a point-in-time dataset holds unadjusted bars; adjusted prices "
            "already fold in corporate actions declared separately here"
        )

    if dataset.corporate_actions.security_id != dataset.series.security_id:
        raise QuantContractError(
            "corporate actions must carry the bar-series security_id; "
            "identity is never inferred from one side"
        )

    # `type(...) is not date` rather than isinstance: a datetime is a date
    # subclass, and a wall-clock instant is not a session.
    if type(dataset.as_of_cutoff) is not date:
        raise QuantContractError("as_of_cutoff must be a date")

    last_session = dataset.series.bars[-1].session
    if dataset.as_of_cutoff < last_session:
        raise QuantContractError(
            f"as_of_cutoff {dataset.as_of_cutoff.isoformat()} precedes the last "
            f"included session {last_session.isoformat()}"
        )

    for action in dataset.corporate_actions.actions:
        if action.effective_session > dataset.as_of_cutoff:
            raise QuantContractError(
                f"corporate action effective {action.effective_session.isoformat()} "
                f"is after the cutoff {dataset.as_of_cutoff.isoformat()}"
            )

    _required_text(dataset.source_id, field="source_id")
    _required_text(dataset.source_revision, field="source_revision")
    if not isinstance(dataset.source_content_sha256, str) or not _SHA256_PATTERN.fullmatch(
        dataset.source_content_sha256
    ):
        raise QuantContractError(
            "source_content_sha256 must be a lowercase 64-character SHA-256 digest"
        )

    if dataset.coverage_scope != "single_security":
        raise QuantContractError(
            "coverage_scope must be single_security; no universe-level "
            "contract exists yet"
        )


def revalidate_dataset(dataset: object) -> PointInTimeDataset:
    """Re-check a receipt at an execution boundary and return it unchanged.

    Raises ``QuantContractError`` for anything that is not a fully valid
    ``PointInTimeDataset``, a mutated one included. No I/O, no clock, and no
    claim about whether the declared source really held this data — this
    checks contract shape and declared provenance, nothing further.
    """

    if not isinstance(dataset, PointInTimeDataset):
        raise QuantContractError(
            "market data enters execution only as a PointInTimeDataset"
        )
    # Children are revalidated by their own owning modules. This module never
    # restates a bar or split rule; a second partial copy would drift.
    revalidate_bar_series(dataset.series)
    revalidate_corporate_action_set(dataset.corporate_actions)
    _check_invariants(dataset)
    return dataset
