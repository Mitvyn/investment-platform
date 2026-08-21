from __future__ import annotations

import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlsplit

from workers.desktop.control import DesktopControlServer
from workers.desktop.security_registry import DesktopSecurityRegistry


class DesktopSecurityRegistryTests(unittest.TestCase):
    def test_keeps_manual_and_moomoo_tickers_in_one_durable_local_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "security-registry.sqlite3"
            registry = DesktopSecurityRegistry(database_path)

            registry.add_manual_ticker("rxrx")
            registry.import_moomoo_symbols(("US.RXRX", "US.CRSP", "HK.00700"))

            self.assertEqual(
                registry.list_entries(),
                (
                    {"sources": ("moomoo_position",), "ticker": "CRSP"},
                    {
                        "sources": ("manual", "moomoo_position"),
                        "ticker": "RXRX",
                    },
                ),
            )

            reloaded = DesktopSecurityRegistry(database_path)
            self.assertEqual(reloaded.list_entries(), registry.list_entries())

    def test_loopback_api_adds_and_lists_manual_tickers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            registry = DesktopSecurityRegistry(
                Path(temporary_directory) / "security-registry.sqlite3"
            )
            server = DesktopControlServer(
                service=object(),  # type: ignore[arg-type]
                control_token="control-secret",
                security_registry=registry,
            )
            server.start()
            self.addCleanup(server.stop)
            parsed = urlsplit(server.origin)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=1)
            connection.request(
                "POST",
                "/v1/security-registry",
                body='{"ticker":"rxrx"}',
                headers={
                    "Authorization": "Bearer control-secret",
                    "Content-Type": "application/json",
                },
            )
            self.assertEqual(connection.getresponse().status, 200)

            connection.request(
                "GET",
                "/v1/security-registry",
                headers={"Authorization": "Bearer control-secret"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(
                response.read(),
                b'{"entries":[{"sources":["manual"],"ticker":"RXRX"}]}',
            )

    def test_loopback_api_imports_only_tickers_from_current_moomoo_mirror(self) -> None:
        class Service:
            @staticmethod
            def holdings() -> object:
                class Mirror:
                    @staticmethod
                    def as_dict() -> dict[str, object]:
                        return {
                            "positions": [
                                {"code": "US.RXRX"},
                                {"code": "US.CRSP"},
                                {"code": "HK.00700"},
                            ]
                        }

                return Mirror()

        with tempfile.TemporaryDirectory() as temporary_directory:
            registry = DesktopSecurityRegistry(
                Path(temporary_directory) / "security-registry.sqlite3"
            )
            server = DesktopControlServer(
                service=Service(),  # type: ignore[arg-type]
                control_token="control-secret",
                security_registry=registry,
            )
            server.start()
            self.addCleanup(server.stop)
            parsed = urlsplit(server.origin)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=1)
            connection.request(
                "POST",
                "/v1/security-registry/import-moomoo",
                body="{}",
                headers={
                    "Authorization": "Bearer control-secret",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(
                response.read(),
                b'{"entries":[{"sources":["moomoo_position"],"ticker":"CRSP"},{"sources":["moomoo_position"],"ticker":"RXRX"}]}',
            )


if __name__ == "__main__":
    unittest.main()
