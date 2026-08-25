"""Bridge from an approved provider transport into the local Quant workspace.

``workers.quant_workspace`` is provider-neutral by design: nothing in it may
import a transport, a network client, or another provider identity, and
``tests/test_quant_workspace_isolation.py`` enforces that as a boundary, not a
convention. This module is deliberately the one place both sides meet. It
lives in ``workers.quant_sources``, the provider layer, which is free to
import the workspace, never the other way around.

The bridge drives an injected
:class:`~workers.quant_sources.transports.HistoricalTransport` through
:class:`~workers.quant_sources.live.LiveQuantSource`, reshapes the exact rows
that receipt was built from into a ``quant_local_dataset.v1`` document, and
persists it through the same
:class:`~workers.quant_workspace.storage.FileQuantWorkspaceStore` a file
import uses. No second dataset contract exists: the document this module
builds is byte-for-byte the same shape a hand-written import file must
satisfy, so a provider-fetched dataset gets the identical restart durability,
tamper re-validation, and result invalidation as a file-imported one.

The document's currency is whatever the provider declared, never assumed.
``LiveQuantSource`` has already checked that value is a well-formed ISO 4217
code before this module ever sees it.
"""

from __future__ import annotations

from datetime import date
from typing import Mapping

from investment_research_os.quant import PointInTimeDataset
from workers.quant_sources.live import LiveQuantSource
from workers.quant_sources.transports import (
    HistoricalTransport,
    TransportBlockedError,
    TransportError,
)
from workers.quant_workspace.intake import (
    LOCAL_DATASET_CONTRACT_VERSION,
    QuantWorkspaceError,
    build_dataset,
    canonical_identity,
)
from workers.quant_workspace.service import (
    DATASET_RECEIPT_CONTRACT_VERSION,
    dataset_receipt,
)
from workers.quant_workspace.storage import FileQuantWorkspaceStore

#: Every code this module can raise on the fetch path itself, before a
#: document ever reaches :func:`build_dataset`. Once a document is built,
#: failures surface through ``build_dataset``'s own reviewed vocabulary
#: instead, because at that point the failure is about the document's
#: contents, not about the fetch.
FETCH_ERROR_CODES = frozenset(
    {
        "fetch_provider_unavailable",
        "fetch_ticker_invalid",
        "fetch_window_invalid",
        "fetch_provider_blocked",
        "fetch_provider_rejected",
    }
)


def fetch_provider_dataset_document(
    transport: HistoricalTransport,
    *,
    ticker: str,
    security_id: str,
    start: date,
    as_of_cutoff: date,
) -> Mapping[str, object]:
    """One provider fetch, shaped as a ``quant_local_dataset.v1`` document.

    Built from the exact rows :class:`LiveAcquisition` carries, never from the
    resulting receipt: the receipt's Decimal values are already normalised
    for Quant's own arithmetic, and hashing a re-derived value instead of the
    provider's declared one would silently break the content hash this
    document exists to carry.
    """

    security_id = canonical_identity(security_id)
    if not isinstance(ticker, str) or not ticker.strip():
        raise QuantWorkspaceError("fetch_ticker_invalid", "ticker is required")
    if type(start) is not date or type(as_of_cutoff) is not date:
        raise QuantWorkspaceError(
            "fetch_window_invalid", "start and as_of_cutoff must be dates"
        )

    try:
        acquisition = LiveQuantSource(transport).acquire_with_rows(
            ticker=ticker,
            security_id=security_id,
            as_of_cutoff=as_of_cutoff,
            start=start,
        )
    except TransportBlockedError as error:
        raise QuantWorkspaceError("fetch_provider_blocked", str(error)) from error
    except TransportError as error:
        raise QuantWorkspaceError("fetch_provider_rejected", str(error)) from error

    dataset = acquisition.dataset
    return {
        "contract_version": LOCAL_DATASET_CONTRACT_VERSION,
        "security_id": security_id,
        "currency": dataset.series.currency,
        "as_of_cutoff": as_of_cutoff.isoformat(),
        "source_id": dataset.source_id,
        "source_revision": dataset.source_revision,
        "source_content_sha256": dataset.source_content_sha256,
        "bars": [dict(row) for row in acquisition.bar_rows],
        "corporate_actions": [dict(row) for row in acquisition.split_rows],
    }


def fetch_provider_dataset(
    transport: HistoricalTransport,
    *,
    ticker: str,
    security_id: str,
    start: date,
    as_of_cutoff: date,
) -> tuple[Mapping[str, object], PointInTimeDataset]:
    """The document above, proved to satisfy intake before anything persists.

    Running the document through :func:`build_dataset` here, rather than only
    at load time, means a fetch that could never be reloaded is refused before
    it is written, instead of being written and only discovered broken on the
    next restart.
    """

    document = fetch_provider_dataset_document(
        transport,
        ticker=ticker,
        security_id=security_id,
        start=start,
        as_of_cutoff=as_of_cutoff,
    )
    dataset = build_dataset(document, security_id=security_id)
    return document, dataset


class ProviderQuantWorkspaceBridge:
    """Fetch one provider dataset and make it the active local dataset.

    A thin analogue of ``DesktopQuantService.import_dataset``, for the one
    operation that service cannot host itself: it lives outside
    ``workers.quant_workspace`` because it must hold a provider transport, and
    the workspace package may not import one.
    """

    def __init__(
        self, store: FileQuantWorkspaceStore, *, transport: HistoricalTransport
    ) -> None:
        self._store = store
        self._transport = transport

    def fetch_dataset(
        self,
        *,
        operator_id: str,
        security_id: str,
        ticker: str,
        start: date,
        as_of_cutoff: date,
    ) -> dict[str, object]:
        """Acquire history from the approved provider and make it active.

        ``ticker`` must already be the caller's own server-derived value from
        the canonical security directory; this bridge has no security
        metadata of its own to check it against, and never looks a ticker up
        itself.

        Like ``import_dataset``, this replaces the active dataset atomically
        and clears any previous result, because the new dataset makes it
        incomparable.
        """

        canonical_identity(operator_id)
        canonical_identity(security_id)
        document, dataset = fetch_provider_dataset(
            self._transport,
            ticker=ticker,
            security_id=security_id,
            start=start,
            as_of_cutoff=as_of_cutoff,
        )
        self._store.save_dataset(
            operator_id=operator_id,
            security_id=security_id,
            document=document,
            dataset_sha256=dataset.content_sha256,
        )
        self._store.save_latest_run_key(
            operator_id=operator_id, security_id=security_id, run_key=None
        )
        return {
            "contract_version": DATASET_RECEIPT_CONTRACT_VERSION,
            "dataset": dataset_receipt(dataset),
            "security_id": security_id,
        }


__all__ = [
    "FETCH_ERROR_CODES",
    "ProviderQuantWorkspaceBridge",
    "fetch_provider_dataset",
    "fetch_provider_dataset_document",
]
