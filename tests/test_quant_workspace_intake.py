from __future__ import annotations

import json
import os
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_research_os.quant import PointInTimeDataset
from investment_research_os.quant_sources import payload_sha256
from workers.quant_workspace.intake import (
    LOCAL_DATASET_CONTRACT_VERSION,
    MAX_DATASET_FILE_BYTES,
    LocalDatasetImportRequest,
    QuantWorkspaceError,
    import_local_dataset,
)

OPERATOR_ID = "3b8f1f4a-9d0e-4a51-9d1b-6c2f0b1d51aa"
SECURITY_ID = "6f1d2c3b-4a5e-4f6a-8b9c-0d1e2f3a4b5c"
OTHER_SECURITY_ID = "11111111-2222-4333-8444-555555555555"


def bar_rows(count: int, *, start_day: int = 1) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(count):
        day = start_day + index
        price = 100 + index
        rows.append(
            {
                "session": f"2026-01-{day:02d}",
                "open": f"{price}.00",
                "high": f"{price + 1}.00",
                "low": f"{price - 1}.00",
                "close": f"{price}.50",
                "volume": 1_000_000,
            }
        )
    return rows


def document(
    *,
    bars: list[dict[str, object]] | None = None,
    splits: list[dict[str, object]] | None = None,
    cutoff: str = "2026-01-20",
    security_id: str = SECURITY_ID,
    currency: str = "USD",
    source_hash: str | None = None,
) -> dict[str, object]:
    rows = bar_rows(10) if bars is None else bars
    split_rows = [] if splits is None else splits
    return {
        "as_of_cutoff": cutoff,
        "bars": rows,
        "contract_version": LOCAL_DATASET_CONTRACT_VERSION,
        "corporate_actions": split_rows,
        "currency": currency,
        "security_id": security_id,
        "source_content_sha256": source_hash
        if source_hash is not None
        else payload_sha256(bar_rows=rows, split_rows=split_rows),
        "source_id": "operator_local_csv",
        "source_revision": "2026-01-20-eod",
    }


def write_document(directory: Path, payload: object, *, name: str = "dataset.json") -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def request_for(path: Path) -> LocalDatasetImportRequest:
    return LocalDatasetImportRequest(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        dataset_path=path,
    )


class LocalDatasetImportTests(unittest.TestCase):
    def assert_rejected(self, path: Path, code: str) -> None:
        with self.assertRaises(QuantWorkspaceError) as caught:
            import_local_dataset(request_for(path))
        self.assertEqual(caught.exception.code, code)

    def test_accepts_a_valid_local_daily_ohlcv_document(self) -> None:
        with TemporaryDirectory() as directory:
            path = write_document(Path(directory), document())
            dataset = import_local_dataset(request_for(path))

            self.assertIsInstance(dataset, PointInTimeDataset)
            self.assertEqual(dataset.security_id, SECURITY_ID)
            self.assertEqual(dataset.as_of_cutoff, date(2026, 1, 20))
            self.assertEqual(dataset.series.currency, "USD")
            self.assertEqual(dataset.series.interval, "1d")
            self.assertEqual(dataset.series.price_basis, "unadjusted")
            self.assertEqual(len(dataset.series.bars), 10)

    def test_relative_or_missing_path_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            self.assert_rejected(Path("dataset.json"), "dataset_path_invalid")
            self.assert_rejected(
                Path(directory) / "absent.json", "dataset_file_unreadable"
            )

    def test_symlinked_dataset_file_or_parent_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            real = write_document(root, document(), name="real.json")
            link = root / "linked.json"
            link.symlink_to(real)
            self.assert_rejected(link, "dataset_path_invalid")

            nested = root / "nested"
            nested.mkdir()
            write_document(nested, document())
            parent_link = root / "linked-dir"
            parent_link.symlink_to(nested)
            self.assert_rejected(parent_link / "dataset.json", "dataset_path_invalid")

    def test_oversized_file_is_rejected_without_parsing(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.json"
            path.write_bytes(b"[" + b" " * (MAX_DATASET_FILE_BYTES + 1))
            self.assert_rejected(path, "dataset_too_large")

    def test_non_json_and_wrong_contract_documents_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            broken = root / "broken.json"
            broken.write_bytes(b"\x00not json at all")
            self.assert_rejected(broken, "dataset_contract_invalid")

            wrong = document()
            wrong["contract_version"] = "quant_local_dataset.v99"
            self.assert_rejected(
                write_document(root, wrong, name="wrong.json"),
                "dataset_contract_invalid",
            )

            extra = document()
            extra["holdings"] = []
            self.assert_rejected(
                write_document(root, extra, name="extra.json"),
                "dataset_contract_invalid",
            )

            missing = document()
            del missing["source_revision"]
            self.assert_rejected(
                write_document(root, missing, name="missing.json"),
                "dataset_contract_invalid",
            )

    def test_document_for_another_security_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            path = write_document(
                Path(directory), document(security_id=OTHER_SECURITY_ID)
            )
            self.assert_rejected(path, "dataset_security_mismatch")

    def test_duplicate_and_out_of_order_sessions_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            rows = bar_rows(4)
            rows[2]["session"] = rows[1]["session"]
            self.assert_rejected(
                write_document(root, document(bars=rows), name="duplicate.json"),
                "dataset_sessions_invalid",
            )

            reordered = bar_rows(4)
            reordered[1], reordered[2] = reordered[2], reordered[1]
            self.assert_rejected(
                write_document(root, document(bars=reordered), name="order.json"),
                "dataset_sessions_invalid",
            )

    def test_bars_after_the_cutoff_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            path = write_document(
                Path(directory), document(cutoff="2026-01-05"), name="future.json"
            )
            self.assert_rejected(path, "dataset_future_data")

    def test_float_prices_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            payload = document(bars=bar_rows(4))
            # Hash first, then swap in a float, so the float itself is what the
            # import must refuse rather than a hash mismatch it causes.
            payload["bars"][0]["close"] = 100.5
            path = write_document(Path(directory), payload)
            self.assert_rejected(path, "dataset_rows_invalid")

    def test_declared_source_hash_must_match_the_payload(self) -> None:
        with TemporaryDirectory() as directory:
            path = write_document(
                Path(directory), document(source_hash="0" * 64)
            )
            self.assert_rejected(path, "dataset_hash_mismatch")

    def test_currency_and_cutoff_must_be_well_formed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assert_rejected(
                write_document(root, document(currency="usd"), name="currency.json"),
                "dataset_currency_invalid",
            )
            self.assert_rejected(
                write_document(root, document(cutoff="20-01-2026"), name="cutoff.json"),
                "dataset_cutoff_invalid",
            )

    def test_splits_are_accepted_only_on_covered_transition_sessions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            covered = [
                {
                    "effective_session": "2026-01-05",
                    "new_shares": 2,
                    "old_shares": 1,
                }
            ]
            dataset = import_local_dataset(
                request_for(
                    write_document(
                        root, document(splits=covered), name="covered.json"
                    )
                )
            )
            self.assertEqual(len(dataset.corporate_actions.actions), 1)

            uncovered = [
                {
                    "effective_session": "2026-01-01",
                    "new_shares": 2,
                    "old_shares": 1,
                }
            ]
            self.assert_rejected(
                write_document(
                    root, document(splits=uncovered), name="uncovered.json"
                ),
                "dataset_split_uncovered",
            )

            after_cutoff = [
                {
                    "effective_session": "2026-01-19",
                    "new_shares": 2,
                    "old_shares": 1,
                }
            ]
            self.assert_rejected(
                write_document(
                    root,
                    document(splits=after_cutoff, cutoff="2026-01-10"),
                    name="split-future.json",
                ),
                "dataset_future_data",
            )

    def test_too_few_sessions_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            path = write_document(Path(directory), document(bars=bar_rows(1)))
            self.assert_rejected(path, "dataset_rows_invalid")

    def test_import_reads_the_file_without_following_a_holdings_field(self) -> None:
        with TemporaryDirectory() as directory:
            rows = bar_rows(4)
            rows[0]["holdings"] = "ignored"
            path = write_document(Path(directory), document(bars=rows))  # noqa: E501
            self.assert_rejected(path, "dataset_rows_invalid")

    def test_import_never_mutates_the_source_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = write_document(Path(directory), document())
            before = path.read_bytes()
            mode_before = os.stat(path).st_mode
            import_local_dataset(request_for(path))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(os.stat(path).st_mode, mode_before)


if __name__ == "__main__":
    unittest.main()
