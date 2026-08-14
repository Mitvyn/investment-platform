from __future__ import annotations

import threading
import unittest
from typing import Mapping

from tests.test_desktop_moomoo_connection import (
    FakeKeychainBackend,
    FakePortfolioClient,
    MoomooTokenKeychain,
    RefreshingOAuthTransport,
    _service_for_completion,
)
from workers.desktop.control import DesktopControlError
from workers.portfolio.quote_stream import (
    MoomooQuoteAccess,
    MoomooQuoteStreamSnapshot,
)


class BlockingRefreshTransport(RefreshingOAuthTransport):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def post_form(
        self,
        url: str,
        *,
        form: Mapping[str, str],
    ) -> Mapping[str, object]:
        self.entered.set()
        self.release.wait(timeout=2)
        return super().post_form(url, form=form)


class BlockingStartQuoteStream:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.stop_count = 0

    def start(self, initial_access: MoomooQuoteAccess) -> None:
        del initial_access
        self.entered.set()
        self.release.wait(timeout=2)

    def replace_symbols(self, symbols: tuple[str, ...]) -> None:
        del symbols

    def snapshot(self) -> MoomooQuoteStreamSnapshot:
        return MoomooQuoteStreamSnapshot("connected", (), (), None)

    def stop(self) -> None:
        self.stop_count += 1


class MoomooResumeConcurrencyTests(unittest.TestCase):
    def test_other_operator_cannot_cancel_pending_resume(self) -> None:
        owner = "11111111-1111-4111-8111-111111111111"
        other = "22222222-2222-4222-8222-222222222222"
        backend = FakeKeychainBackend()
        MoomooTokenKeychain(operator_id=owner, backend=backend).store_refresh_token(
            "refresh-secret"
        )
        transport = BlockingRefreshTransport()
        service, _opened = _service_for_completion(
            oauth_transport=transport,
            keychain_backend=backend,
        )
        errors: list[BaseException] = []

        def run_resume() -> None:
            try:
                service.resume_connection(
                    client_id="4a8bcd69-e915-4778-9583-17ad0e9e6a80",
                    operator_id=owner,
                )
            except BaseException as error:  # pragma: no branch - asserted below
                errors.append(error)

        resume = threading.Thread(target=run_resume)
        resume.start()
        self.assertTrue(transport.entered.wait(timeout=1))

        with self.assertRaisesRegex(
            DesktopControlError,
            "moomoo_connected_operator_mismatch",
        ):
            service.disconnect(operator_id=other)

        transport.release.set()
        resume.join(timeout=2)
        self.assertFalse(resume.is_alive())
        self.assertEqual(errors, [])

    def test_disconnect_during_resume_stops_started_stream_and_wins_state(self) -> None:
        owner = "11111111-1111-4111-8111-111111111111"
        backend = FakeKeychainBackend()
        MoomooTokenKeychain(operator_id=owner, backend=backend).store_refresh_token(
            "refresh-secret"
        )
        stream = BlockingStartQuoteStream()
        service, _opened = _service_for_completion(
            oauth_transport=RefreshingOAuthTransport(),
            keychain_backend=backend,
            portfolio_client_factory=lambda _token: FakePortfolioClient(),
            quote_stream_factory=lambda _supplier: stream,
        )
        errors: list[BaseException] = []

        def resume() -> None:
            try:
                service.resume_connection(
                    client_id="4a8bcd69-e915-4778-9583-17ad0e9e6a80",
                    operator_id=owner,
                )
            except BaseException as error:  # pragma: no branch - asserted below
                errors.append(error)

        thread = threading.Thread(target=resume)
        thread.start()
        self.assertTrue(stream.entered.wait(timeout=1))

        status = service.disconnect(operator_id=owner)
        stream.release.set()
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(status.state, "disconnected")
        self.assertEqual(service.status().state, "disconnected")
        self.assertEqual(stream.stop_count, 1)
        self.assertEqual(
            [str(error) for error in errors],
            ["moomoo_connection_changed"],
        )


if __name__ == "__main__":
    unittest.main()
