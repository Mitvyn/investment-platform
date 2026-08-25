"""The desktop-facing Quant workspace service.

Three operations, one security at a time: report what dataset is active, import
a new one from a local file, and run an analysis. Everything is local, offline,
and deterministic. No provider, model, broker, or hosted database is reachable
from here, and no Research or Portfolio state is readable.

The service is the last place a rich internal object exists. Everything it
returns is a sanitized record built for a browser: identity hashes, declared
assumptions, aggregate numbers, and codes. Bars, rows, prices, and file
contents stay on this side of the boundary.

A run is idempotent by identity. The run key is a function of the dataset hash
and the declared assumptions, so repeating a request after a restart reloads
the stored record rather than recomputing one that might not match.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from investment_research_os.quant import PointInTimeDataset
from workers.quant_workspace import intake
from workers.quant_workspace.intake import QuantWorkspaceError, build_dataset
from workers.quant_workspace.runner import (
    assumptions_from_mapping,
    run_key,
    run_quant_analysis,
)
from workers.quant_workspace.storage import FileQuantWorkspaceStore

DATASET_RECEIPT_CONTRACT_VERSION = "quant_local_dataset_receipt.v1"


def _dataset_receipt(dataset: PointInTimeDataset) -> dict[str, object]:
    """What the browser may know about a dataset.

    Counts, dates, identities, and hashes. Never a bar, a price, or a row: the
    operator already has the file, and the workspace has no reason to send its
    contents back to them through a second surface.
    """

    return {
        "as_of_cutoff": dataset.as_of_cutoff.isoformat(),
        "corporate_actions_sha256": dataset.corporate_actions.content_sha256,
        "currency": dataset.series.currency,
        "dataset_sha256": dataset.content_sha256,
        "first_session": dataset.series.bars[0].session.isoformat(),
        "interval": dataset.series.interval,
        "last_session": dataset.series.bars[-1].session.isoformat(),
        "price_basis": dataset.series.price_basis,
        "series_sha256": dataset.series.content_sha256,
        "session_count": len(dataset.series.bars),
        "source_content_sha256": dataset.source_content_sha256,
        "source_id": dataset.source_id,
        "source_revision": dataset.source_revision,
        "split_count": len(dataset.corporate_actions.actions),
    }


class DesktopQuantService:
    """Local Quant workspace operations for one operator at a time."""

    def __init__(self, store: FileQuantWorkspaceStore) -> None:
        self._store = store

    def _active_dataset(
        self, *, operator_id: str, security_id: str
    ) -> PointInTimeDataset | None:
        """Rebuild the stored dataset through the intake rules, or report none.

        The stored document is re-validated on every load rather than trusted,
        and the rebuilt receipt must hash to the value recorded at import time.
        A document that no longer satisfies intake, or that no longer produces
        its recorded hash, reads as no dataset at all: the operator imports
        again rather than analysing something that changed underneath them.
        """

        stored = self._store.load_dataset(
            operator_id=operator_id, security_id=security_id
        )
        if stored is None:
            return None
        try:
            dataset = build_dataset(stored.document, security_id=security_id)
        except QuantWorkspaceError:
            return None
        if dataset.content_sha256 != stored.dataset_sha256:
            return None
        return dataset

    def dataset_status(
        self, *, operator_id: str, security_id: str
    ) -> dict[str, object]:
        """The active dataset for one security, or an explicit absence."""

        dataset = self._active_dataset(
            operator_id=operator_id, security_id=security_id
        )
        return {
            "contract_version": DATASET_RECEIPT_CONTRACT_VERSION,
            "dataset": None if dataset is None else _dataset_receipt(dataset),
            "security_id": security_id,
        }

    def import_dataset(
        self, *, operator_id: str, security_id: str, dataset_path: Path
    ) -> dict[str, object]:
        """Validate one local file and make it the active dataset.

        Validation happens before persistence, so a rejected file never becomes
        the active dataset and never displaces a working one.
        """

        # Read once. Validating one read and persisting a second would leave a
        # window in which the two differ, and the stored document would be one
        # nothing had checked.
        # Both identities are checked here as well as by the store: a path
        # segment is never derived from anything that has not been through this.
        intake.canonical_identity(operator_id)
        intake.canonical_identity(security_id)
        document = intake.read_local_dataset_document(dataset_path)
        dataset = build_dataset(document, security_id=security_id)
        self._store.save_dataset(
            operator_id=operator_id,
            security_id=security_id,
            document=document,
            dataset_sha256=dataset.content_sha256,
        )
        # A new dataset makes any previously displayed result incomparable, so
        # the pointer is cleared rather than left aiming at a number computed
        # against a file that is no longer active. The stored record itself
        # stays: it is addressed by its own dataset hash and can be reloaded by
        # repeating that exact request.
        self._store.save_latest_run_key(
            operator_id=operator_id, security_id=security_id, run_key=None
        )
        return {
            "contract_version": DATASET_RECEIPT_CONTRACT_VERSION,
            "dataset": _dataset_receipt(dataset),
            "security_id": security_id,
        }

    def latest_result(
        self, *, operator_id: str, security_id: str
    ) -> Mapping[str, object] | None:
        """The last completed run for the active dataset, if there is one."""

        key = self._store.load_latest_run_key(
            operator_id=operator_id, security_id=security_id
        )
        if key is None:
            return None
        return self._store.load_result(
            operator_id=operator_id, security_id=security_id, run_key=key
        )

    def run_analysis(
        self,
        *,
        operator_id: str,
        security_id: str,
        assumptions: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Run, or reload, one historical analysis for one security.

        The result is historical analysis of an operator-supplied dataset. It
        is not a prediction, not a recommendation, and not evidence for any
        Research artifact.
        """

        declared = assumptions_from_mapping(assumptions)
        dataset = self._active_dataset(
            operator_id=operator_id, security_id=security_id
        )
        if dataset is None:
            raise QuantWorkspaceError(
                "run_dataset_missing", "no active dataset for this security"
            )
        key = run_key(dataset_sha256=dataset.content_sha256, assumptions=declared)
        stored = self._store.load_result(
            operator_id=operator_id, security_id=security_id, run_key=key
        )
        if stored is not None:
            self._store.save_latest_run_key(
                operator_id=operator_id, security_id=security_id, run_key=key
            )
            return stored
        record = run_quant_analysis(dataset=dataset, assumptions=declared)
        self._store.save_result(
            operator_id=operator_id,
            security_id=security_id,
            run_key=key,
            record=record,
        )
        self._store.save_latest_run_key(
            operator_id=operator_id, security_id=security_id, run_key=key
        )
        return record
