from __future__ import annotations

import json
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from unittest import mock

from investment_research_os.quant_sources import payload_sha256
from workers.quant_workspace import intake
from workers.desktop.control import DesktopControlServer, MoomooConnectionService
from workers.portfolio.keychain import MoomooTokenKeychain
from workers.quant_workspace.intake import QuantWorkspaceError
from workers.quant_workspace.service import DesktopQuantService
from workers.quant_workspace.storage import FileQuantWorkspaceStore

OPERATOR_ID = "3b8f1f4a-9d0e-4a51-9d1b-6c2f0b1d51aa"
SECURITY_ID = "6f1d2c3b-4a5e-4f6a-8b9c-0d1e2f3a4b5c"
OTHER_SECURITY_ID = "11111111-2222-4333-8444-555555555555"

ASSUMPTIONS: dict[str, object] = {
    "alpha": "0.05",
    "annualisation_periods": 252,
    "commission_bps": "0",
    "commission_minimum": "1.00",
    "commission_per_share": "0.01",
    "cost_stress_multiplier": "3",
    "embargo_sessions": 1,
    "lookback_sessions": 5,
    "max_participation_bps": "500",
    "min_fill_shares": 1,
    "min_total_trades": 1,
    "min_trades_per_window": 0,
    "min_windows": 3,
    "slippage_bps": "5",
    "starting_cash": "100000.00",
    "step_sessions": 10,
    "test_sessions": 10,
    "train_sessions": 20,
    "transaction_cost_bps": "2",
    "trials_declared": 2,
}


def bar_rows(count: int) -> list[dict[str, object]]:
    start = date(2025, 1, 6)
    rows: list[dict[str, object]] = []
    for index in range(count):
        price = 100 + (index % 7)
        rows.append(
            {
                "close": f"{price}.00",
                "high": f"{price + 1}.00",
                "low": f"{price - 1}.00",
                "open": f"{price}.00",
                "session": (start + timedelta(days=index)).isoformat(),
                "volume": 1_000_000,
            }
        )
    return rows


def document(*, security_id: str = SECURITY_ID, count: int = 80) -> dict[str, object]:
    rows = bar_rows(count)
    return {
        "as_of_cutoff": str(rows[-1]["session"]),
        "bars": rows,
        "contract_version": "quant_local_dataset.v1",
        "corporate_actions": [],
        "currency": "USD",
        "security_id": security_id,
        "source_content_sha256": payload_sha256(bar_rows=rows, split_rows=[]),
        "source_id": "operator_local_csv",
        "source_revision": "2026-01-20-eod",
    }


def write_document(directory: Path, payload: object) -> Path:
    path = directory / "dataset.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class _KeychainBackend:
    """In-memory stand-in so no test ever reaches the real Keychain."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], str] = {}

    def get(self, service: str, account: str) -> str | None:
        return self._items.get((service, account))

    def set(self, service: str, account: str, secret: str) -> None:
        self._items[(service, account)] = secret

    def delete(self, service: str, account: str) -> None:
        self._items.pop((service, account), None)


class _OAuthTransport:
    """Never called: the Quant routes touch no broker path at all."""

    def exchange(self, *args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("Quant routes must not reach a broker transport")

    def refresh(self, *args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("Quant routes must not reach a broker transport")


def _idle_moomoo_service() -> MoomooConnectionService:
    backend = _KeychainBackend()
    return MoomooConnectionService(
        keychain_factory=lambda operator_id: MoomooTokenKeychain(
            operator_id=operator_id, backend=backend
        ),
        oauth_transport=_OAuthTransport(),
    )


def service_for(root: Path) -> DesktopQuantService:
    return DesktopQuantService(FileQuantWorkspaceStore(root))


class DesktopQuantServiceTests(unittest.TestCase):
    def test_dataset_status_is_absent_before_any_import(self) -> None:
        with TemporaryDirectory() as directory:
            status = service_for(Path(directory) / "quant").dataset_status(
                operator_id=OPERATOR_ID, security_id=SECURITY_ID
            )
            self.assertEqual(
                status,
                {
                    "contract_version": "quant_local_dataset_receipt.v1",
                    "dataset": None,
                    "security_id": SECURITY_ID,
                },
            )

    def test_import_returns_a_receipt_and_persists_the_dataset(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_document(root, document())
            receipt = service_for(root / "quant").import_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                dataset_path=path,
            )

            self.assertEqual(receipt["security_id"], SECURITY_ID)
            dataset = receipt["dataset"]
            assert isinstance(dataset, dict)
            self.assertEqual(dataset["session_count"], 80)
            self.assertEqual(dataset["currency"], "USD")
            self.assertEqual(dataset["source_id"], "operator_local_csv")
            self.assertEqual(len(str(dataset["dataset_sha256"])), 64)
            self.assertNotIn("bars", dataset)

            reloaded = service_for(root / "quant").dataset_status(
                operator_id=OPERATOR_ID, security_id=SECURITY_ID
            )
            self.assertEqual(reloaded, receipt)

    def test_import_refuses_a_document_for_another_security(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_document(root, document(security_id=OTHER_SECURITY_ID))
            with self.assertRaises(QuantWorkspaceError) as caught:
                service_for(root / "quant").import_dataset(
                    operator_id=OPERATOR_ID,
                    security_id=SECURITY_ID,
                    dataset_path=path,
                )
            self.assertEqual(caught.exception.code, "dataset_security_mismatch")

    def test_run_requires_an_imported_dataset(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(QuantWorkspaceError) as caught:
                service_for(Path(directory) / "quant").run_analysis(
                    operator_id=OPERATOR_ID,
                    security_id=SECURITY_ID,
                    assumptions=ASSUMPTIONS,
                )
            self.assertEqual(caught.exception.code, "run_dataset_missing")

    def test_run_is_deterministic_across_worker_restarts(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_document(root, document())
            service_for(root / "quant").import_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                dataset_path=path,
            )

            first = service_for(root / "quant").run_analysis(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                assumptions=ASSUMPTIONS,
            )
            # A fresh service instance stands in for a restarted worker: it
            # shares only the directory, never in-memory state.
            second = service_for(root / "quant").run_analysis(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                assumptions=ASSUMPTIONS,
            )

            self.assertEqual(first["content_sha256"], second["content_sha256"])
            self.assertEqual(first, second)

    def test_run_result_is_reloaded_rather_than_recomputed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_document(root, document())
            service = service_for(root / "quant")
            service.import_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                dataset_path=path,
            )
            first = service.run_analysis(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                assumptions=ASSUMPTIONS,
            )

            results = [
                path
                for path in (root / "quant" / "results").rglob("*.json")
                if path.name != "latest.json"
            ]
            self.assertEqual(len(results), 1)
            self.assertEqual(
                json.loads(results[0].read_text(encoding="utf-8")), first
            )

    def test_import_stores_exactly_the_document_it_validated(self) -> None:
        """One read, not two.

        Validating one read of the file and then persisting a second read of it
        leaves a window in which the two differ. The stored document would then
        be one nothing checked, and the receipt handed back would describe a
        dataset that was never stored.
        """

        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_document(root, document())
            service = service_for(root / "quant")

            reads: list[Path] = []
            original = intake.read_local_dataset_document

            def counting_read(target: object) -> object:
                reads.append(target)  # type: ignore[arg-type]
                return original(target)

            with mock.patch.object(
                intake, "read_local_dataset_document", counting_read
            ):
                receipt = service.import_dataset(
                    operator_id=OPERATOR_ID,
                    security_id=SECURITY_ID,
                    dataset_path=path,
                )

            self.assertEqual(len(reads), 1)
            stored = service.dataset_status(
                operator_id=OPERATOR_ID, security_id=SECURITY_ID
            )
            self.assertEqual(stored, receipt)

    def test_import_receipt_always_describes_the_stored_document(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_document(root, document())
            service = service_for(root / "quant")

            swapped = document(count=70)
            unpatched = intake.read_local_dataset_document

            def swapping_read(target: object) -> object:
                # Stands in for the file changing between validation and
                # persistence. Whatever is stored must be what was validated.
                result = unpatched(target)
                path.write_text(json.dumps(swapped), encoding="utf-8")
                return result

            with mock.patch.object(
                intake, "read_local_dataset_document", swapping_read
            ):
                receipt = service.import_dataset(
                    operator_id=OPERATOR_ID,
                    security_id=SECURITY_ID,
                    dataset_path=path,
                )

            reloaded = service.dataset_status(
                operator_id=OPERATOR_ID, security_id=SECURITY_ID
            )
            self.assertEqual(reloaded["dataset"], receipt["dataset"])

    def test_latest_result_is_absent_until_a_run_completes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_document(root, document())
            service = service_for(root / "quant")
            self.assertIsNone(
                service.latest_result(
                    operator_id=OPERATOR_ID, security_id=SECURITY_ID
                )
            )
            service.import_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                dataset_path=path,
            )
            self.assertIsNone(
                service.latest_result(
                    operator_id=OPERATOR_ID, security_id=SECURITY_ID
                )
            )

    def test_latest_result_reloads_the_last_run_after_a_restart(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_document(root, document())
            service_for(root / "quant").import_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                dataset_path=path,
            )
            produced = service_for(root / "quant").run_analysis(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                assumptions=ASSUMPTIONS,
            )

            self.assertEqual(
                service_for(root / "quant").latest_result(
                    operator_id=OPERATOR_ID, security_id=SECURITY_ID
                ),
                produced,
            )

    def test_latest_result_is_dropped_when_the_dataset_is_replaced(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            service = service_for(root / "quant")
            service.import_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                dataset_path=write_document(root, document()),
            )
            service.run_analysis(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                assumptions=ASSUMPTIONS,
            )
            # A different dataset invalidates the displayed result: a number
            # computed against the previous file must never be shown beside a
            # newly imported one.
            service.import_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                dataset_path=write_document(root, document(count=70)),
            )

            self.assertIsNone(
                service.latest_result(
                    operator_id=OPERATOR_ID, security_id=SECURITY_ID
                )
            )

    def test_run_refuses_unsupported_assumptions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_document(root, document())
            service = service_for(root / "quant")
            service.import_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                dataset_path=root / "dataset.json",
            )
            broken = dict(ASSUMPTIONS)
            broken["holdings_value"] = "100"
            with self.assertRaises(QuantWorkspaceError) as caught:
                service.run_analysis(
                    operator_id=OPERATOR_ID,
                    security_id=SECURITY_ID,
                    assumptions=broken,
                )
            self.assertEqual(caught.exception.code, "run_assumptions_invalid")

    def test_datasets_and_results_never_cross_securities(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_document(root, document())
            service = service_for(root / "quant")
            service.import_dataset(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                dataset_path=path,
            )

            self.assertIsNone(
                service.dataset_status(
                    operator_id=OPERATOR_ID, security_id=OTHER_SECURITY_ID
                )["dataset"]
            )
            with self.assertRaises(QuantWorkspaceError) as caught:
                service.run_analysis(
                    operator_id=OPERATOR_ID,
                    security_id=OTHER_SECURITY_ID,
                    assumptions=ASSUMPTIONS,
                )
            self.assertEqual(caught.exception.code, "run_dataset_missing")


class DesktopQuantRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.token = "quant-control-token-value-for-tests"
        self.server = DesktopControlServer(
            service=_idle_moomoo_service(),
            control_token=self.token,
            quant_service=service_for(self.root / "quant"),
        )
        self.server.start()
        self.addCleanup(self.server.stop)

    def request(
        self, path: str, *, body: object | None = None, token: str | None = None
    ) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.server.origin}{path}",
            data=data,
            headers={
                "Authorization": f"Bearer {self.token if token is None else token}",
                "Content-Type": "application/json",
            },
            method="GET" if data is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_dataset_route_requires_authorization(self) -> None:
        status, payload = self.request(
            f"/v1/quant/dataset?operator_id={OPERATOR_ID}&security_id={SECURITY_ID}",
            token="wrong-token",
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload, {"error": "desktop_control_unauthorized"})

    def test_dataset_route_reports_an_absent_dataset(self) -> None:
        status, payload = self.request(
            f"/v1/quant/dataset?operator_id={OPERATOR_ID}&security_id={SECURITY_ID}"
        )
        self.assertEqual(status, 200)
        assert isinstance(payload, dict)
        self.assertIsNone(payload["dataset"])

    def test_import_and_run_routes_complete_the_workspace(self) -> None:
        path = write_document(self.root, document())

        status, receipt = self.request(
            "/v1/quant/dataset/import",
            body={
                "dataset_path": str(path),
                "operator_id": OPERATOR_ID,
                "security_id": SECURITY_ID,
            },
        )
        self.assertEqual(status, 200)
        assert isinstance(receipt, dict)
        assert isinstance(receipt["dataset"], dict)
        self.assertEqual(receipt["dataset"]["session_count"], 80)

        status, result = self.request(
            "/v1/quant/runs",
            body={
                "assumptions": ASSUMPTIONS,
                "operator_id": OPERATOR_ID,
                "security_id": SECURITY_ID,
            },
        )
        self.assertEqual(status, 200)
        assert isinstance(result, dict)
        self.assertEqual(result["contract_version"], "quant_local_result.v1")
        self.assertEqual(result["security_id"], SECURITY_ID)
        self.assertIn("strategy", result)
        self.assertIn("benchmark", result)
        self.assertIn("validation", result)

    def test_import_route_returns_a_bounded_error_code(self) -> None:
        status, payload = self.request(
            "/v1/quant/dataset/import",
            body={
                "dataset_path": str(self.root / "absent.json"),
                "operator_id": OPERATOR_ID,
                "security_id": SECURITY_ID,
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(
            payload,
            {"error": "quant_request_invalid", "reason": "dataset_file_unreadable"},
        )

    def test_latest_run_route_reports_an_absent_result(self) -> None:
        status, payload = self.request(
            f"/v1/quant/runs/latest?operator_id={OPERATOR_ID}"
            f"&security_id={SECURITY_ID}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"result": None})

    def test_latest_run_route_returns_the_last_completed_result(self) -> None:
        write_document(self.root, document())
        self.request(
            "/v1/quant/dataset/import",
            body={
                "dataset_path": str(self.root / "dataset.json"),
                "operator_id": OPERATOR_ID,
                "security_id": SECURITY_ID,
            },
        )
        _, produced = self.request(
            "/v1/quant/runs",
            body={
                "assumptions": ASSUMPTIONS,
                "operator_id": OPERATOR_ID,
                "security_id": SECURITY_ID,
            },
        )

        status, payload = self.request(
            f"/v1/quant/runs/latest?operator_id={OPERATOR_ID}"
            f"&security_id={SECURITY_ID}"
        )
        self.assertEqual(status, 200)
        assert isinstance(payload, dict)
        self.assertEqual(payload["result"], produced)

    def test_run_route_reports_a_missing_dataset_without_leaking_detail(self) -> None:
        status, payload = self.request(
            "/v1/quant/runs",
            body={
                "assumptions": ASSUMPTIONS,
                "operator_id": OPERATOR_ID,
                "security_id": SECURITY_ID,
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(
            payload,
            {"error": "quant_request_invalid", "reason": "run_dataset_missing"},
        )

    def test_quant_routes_reject_unexpected_fields(self) -> None:
        for path, body in (
            (
                "/v1/quant/dataset/import",
                {
                    "dataset_path": "/tmp/x.json",
                    "holdings": [],
                    "operator_id": OPERATOR_ID,
                    "security_id": SECURITY_ID,
                },
            ),
            (
                "/v1/quant/runs",
                {
                    "assumptions": ASSUMPTIONS,
                    "operator_id": OPERATOR_ID,
                    "portfolio_value": "1",
                    "security_id": SECURITY_ID,
                },
            ),
        ):
            with self.subTest(path=path):
                status, payload = self.request(path, body=body)
                self.assertEqual(status, 400)
                assert isinstance(payload, dict)
                self.assertEqual(payload["error"], "quant_request_invalid")


if __name__ == "__main__":
    unittest.main()
