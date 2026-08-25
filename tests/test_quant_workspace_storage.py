from __future__ import annotations

import json
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from workers.quant_workspace.intake import QuantWorkspaceError
from workers.quant_workspace.storage import FileQuantWorkspaceStore

OPERATOR_ID = "3b8f1f4a-9d0e-4a51-9d1b-6c2f0b1d51aa"
SECURITY_ID = "6f1d2c3b-4a5e-4f6a-8b9c-0d1e2f3a4b5c"
OTHER_SECURITY_ID = "11111111-2222-4333-8444-555555555555"

DOCUMENT: dict[str, object] = {
    "as_of_cutoff": "2026-01-20",
    "bars": [
        {
            "session": "2026-01-01",
            "open": "100.00",
            "high": "101.00",
            "low": "99.00",
            "close": "100.50",
            "volume": 1_000_000,
        }
    ],
    "contract_version": "quant_local_dataset.v1",
    "corporate_actions": [],
    "currency": "USD",
    "security_id": SECURITY_ID,
    "source_content_sha256": "b" * 64,
    "source_id": "operator_local_csv",
    "source_revision": "2026-01-20-eod",
}

RESULT: dict[str, object] = {
    "content_sha256": "c" * 64,
    "contract_version": "quant_local_result.v1",
    "security_id": SECURITY_ID,
}


class QuantWorkspaceStoreTests(unittest.TestCase):
    def test_saved_dataset_survives_a_new_store_instance(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "quant"
            FileQuantWorkspaceStore(root).save_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                document=DOCUMENT,
                dataset_sha256="d" * 64,
            )

            reloaded = FileQuantWorkspaceStore(root).load_dataset(
                operator_id=OPERATOR_ID, security_id=SECURITY_ID
            )

            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            self.assertEqual(reloaded.document, DOCUMENT)
            self.assertEqual(reloaded.dataset_sha256, "d" * 64)

    def test_datasets_are_scoped_by_operator_and_security(self) -> None:
        with TemporaryDirectory() as directory:
            store = FileQuantWorkspaceStore(Path(directory))
            store.save_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                document=DOCUMENT,
                dataset_sha256="d" * 64,
            )

            self.assertIsNone(
                store.load_dataset(
                    operator_id=OPERATOR_ID, security_id=OTHER_SECURITY_ID
                )
            )
            self.assertIsNone(
                store.load_dataset(
                    operator_id=OTHER_SECURITY_ID, security_id=SECURITY_ID
                )
            )

    def test_absent_dataset_and_result_read_as_missing(self) -> None:
        with TemporaryDirectory() as directory:
            store = FileQuantWorkspaceStore(Path(directory))
            self.assertIsNone(
                store.load_dataset(operator_id=OPERATOR_ID, security_id=SECURITY_ID)
            )
            self.assertIsNone(
                store.load_result(
                    operator_id=OPERATOR_ID,
                    security_id=SECURITY_ID,
                    run_key="e" * 64,
                )
            )

    def test_saved_result_reloads_by_run_key(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            FileQuantWorkspaceStore(root).save_result(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                run_key="e" * 64,
                record=RESULT,
            )

            self.assertEqual(
                FileQuantWorkspaceStore(root).load_result(
                    operator_id=OPERATOR_ID,
                    security_id=SECURITY_ID,
                    run_key="e" * 64,
                ),
                RESULT,
            )

    def test_stored_files_are_owner_only_and_stay_inside_the_root(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "quant"
            store = FileQuantWorkspaceStore(root)
            store.save_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                document=DOCUMENT,
                dataset_sha256="d" * 64,
            )
            store.save_result(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                run_key="e" * 64,
                record=RESULT,
            )

            files = [path for path in root.rglob("*") if path.is_file()]
            self.assertEqual(len(files), 2)
            for path in files:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertTrue(str(path.resolve()).startswith(str(root.resolve())))

    def test_symlinked_operator_or_security_directory_is_refused(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "quant"
            elsewhere = Path(directory) / "elsewhere"
            elsewhere.mkdir(parents=True)
            (root / "datasets").mkdir(parents=True)
            (root / "datasets" / OPERATOR_ID).symlink_to(elsewhere)

            store = FileQuantWorkspaceStore(root)
            with self.assertRaises(QuantWorkspaceError) as caught:
                store.save_dataset(
                    operator_id=OPERATOR_ID,
                    security_id=SECURITY_ID,
                    document=DOCUMENT,
                    dataset_sha256="d" * 64,
                )
            self.assertEqual(caught.exception.code, "workspace_store_unsafe")
            self.assertIsNone(
                store.load_dataset(operator_id=OPERATOR_ID, security_id=SECURITY_ID)
            )

    def test_non_canonical_identity_never_reaches_the_filesystem(self) -> None:
        with TemporaryDirectory() as directory:
            store = FileQuantWorkspaceStore(Path(directory))
            for operator_id, security_id in (
                ("../escape", SECURITY_ID),
                (OPERATOR_ID, "../escape"),
                (OPERATOR_ID, "not-a-uuid"),
            ):
                with self.subTest(operator_id=operator_id, security_id=security_id):
                    with self.assertRaises(QuantWorkspaceError):
                        store.save_dataset(
                            operator_id=operator_id,
                            security_id=security_id,
                            document=DOCUMENT,
                            dataset_sha256="d" * 64,
                        )
            self.assertEqual(list(Path(directory).rglob("*")), [])

    def test_corrupt_or_tampered_records_read_as_missing(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = FileQuantWorkspaceStore(root)
            store.save_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                document=DOCUMENT,
                dataset_sha256="d" * 64,
            )
            stored = next(path for path in root.rglob("*.json") if path.is_file())

            stored.write_text("{ not json", encoding="utf-8")
            self.assertIsNone(
                store.load_dataset(operator_id=OPERATOR_ID, security_id=SECURITY_ID)
            )

            record = json.loads(json.dumps({"contract_version": "wrong"}))
            stored.write_text(json.dumps(record), encoding="utf-8")
            self.assertIsNone(
                store.load_dataset(operator_id=OPERATOR_ID, security_id=SECURITY_ID)
            )

    def test_reimport_replaces_the_active_dataset_for_that_security(self) -> None:
        with TemporaryDirectory() as directory:
            store = FileQuantWorkspaceStore(Path(directory))
            store.save_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                document=DOCUMENT,
                dataset_sha256="d" * 64,
            )
            replacement = dict(DOCUMENT)
            replacement["source_revision"] = "2026-02-01-eod"
            store.save_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                document=replacement,
                dataset_sha256="f" * 64,
            )

            reloaded = store.load_dataset(
                operator_id=OPERATOR_ID, security_id=SECURITY_ID
            )
            assert reloaded is not None
            self.assertEqual(reloaded.dataset_sha256, "f" * 64)
            self.assertEqual(
                reloaded.document["source_revision"], "2026-02-01-eod"
            )


if __name__ == "__main__":
    unittest.main()
