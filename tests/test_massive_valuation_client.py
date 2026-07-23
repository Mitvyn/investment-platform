from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from io import BytesIO
from threading import Barrier, Event, Lock, Thread
from time import sleep
from typing import Any, Mapping
from urllib.error import HTTPError

from investment_research_os.valuation_snapshots.massive import (
    MassiveHttpTransport,
    MassiveNoRedirectHandler,
    MassiveRateLimitError,
    MassiveRequestCoordinator,
    MassiveRollingRateLimiter,
    MassiveSettings,
    MassiveValuationClient,
)
from workers.sec.storage import JsonResponse


class MassiveTransportFake:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, Mapping[str, str]]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        self.requests.append((method, url, headers))
        return JsonResponse(
            payload={
                "status": "OK",
                "symbol": "RXRX",
                "from": "2026-05-06",
                "open": 6.10,
                "high": 6.40,
                "low": 6.02,
                "close": 6.25,
                "volume": 1234567,
            },
            status=200,
            headers={},
        )


class RateLimitTransportFake:
    def __init__(self, clock) -> None:
        self.clock = clock
        self.request_times: list[float] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        self.request_times.append(self.clock())
        session_text = url.split("/")[-1].split("?")[0]
        return JsonResponse(
            payload={
                "status": "OK",
                "symbol": "RXRX",
                "from": session_text,
                "open": 6.10,
                "high": 6.40,
                "low": 6.02,
                "close": 6.25,
                "volume": 1234567,
            },
            status=200,
            headers={},
        )


class QuotaResponseFake:
    def __init__(self, retry_after: str = "47") -> None:
        self.request_count = 0
        self.retry_after = retry_after

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        self.request_count += 1
        return JsonResponse(
            payload={"status": "ERROR", "error": "rate limit exceeded"},
            status=429,
            headers={"Retry-After": self.retry_after},
        )


class NoopRateLimiter:
    def acquire(self) -> None:
        return None


class DelayedMassiveTransportFake(MassiveTransportFake):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()
        self.lock = Lock()

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        with self.lock:
            self.requests.append((method, url, headers))
            self.entered.set()
        self.release.wait(timeout=1.0)
        return JsonResponse(
            payload={
                "status": "OK",
                "symbol": "RXRX",
                "from": "2026-05-06",
                "open": 6.10,
                "high": 6.40,
                "low": 6.02,
                "close": 6.25,
                "volume": 1234567,
            },
            status=200,
            headers={},
        )


class MassiveValuationClientTests(unittest.TestCase):
    def test_http_transport_refuses_redirects_before_forwarding_bearer_key(
        self,
    ) -> None:
        redirected_request = MassiveNoRedirectHandler().redirect_request(
            req=object(),
            fp=None,
            code=302,
            msg="Found",
            headers={"Location": "https://example.invalid/collect"},
            newurl="https://example.invalid/collect",
        )

        self.assertIsNone(redirected_request)

    def test_http_transport_preserves_429_status_and_retry_headers(self) -> None:
        def raise_rate_limit(*args, **kwargs):
            raise HTTPError(
                url="https://api.massive.com/test",
                code=429,
                msg="Too Many Requests",
                hdrs={"Retry-After": "47"},
                fp=BytesIO(b'{"status":"ERROR"}'),
            )

        response = MassiveHttpTransport(
            timeout_seconds=10.0,
            request_executor=raise_rate_limit,
        ).request_json(
            "GET",
            "https://api.massive.com/test",
            headers={"Authorization": "Bearer test"},
        )

        self.assertEqual(response.status, 429)
        self.assertEqual(response.headers["Retry-After"], "47")
        self.assertEqual(response.payload, {"status": "ERROR"})

    def test_http_transport_preserves_non_json_429_status_and_headers(self) -> None:
        def raise_rate_limit(*args, **kwargs):
            raise HTTPError(
                url="https://api.massive.com/test",
                code=429,
                msg="Too Many Requests",
                hdrs={"Retry-After": "120"},
                fp=BytesIO(b"rate limit exceeded"),
            )

        response = MassiveHttpTransport(
            timeout_seconds=10.0,
            request_executor=raise_rate_limit,
        ).request_json(
            "GET",
            "https://api.massive.com/test",
            headers={"Authorization": "Bearer test"},
        )

        self.assertEqual(response.status, 429)
        self.assertEqual(response.headers["Retry-After"], "120")
        self.assertIsNone(response.payload)

    def test_loads_server_only_key_without_exposing_it_in_settings_repr(
        self,
    ) -> None:
        settings = MassiveSettings.from_environment(
            {"MASSIVE_API_KEY": "massive_test_key"}
        )

        self.assertEqual(settings.api_key, "massive_test_key")
        self.assertNotIn("massive_test_key", repr(settings))

    def test_default_clients_share_one_process_quota_coordinator(self) -> None:
        first = MassiveValuationClient(
            MassiveSettings(api_key="massive_test_key"),
        )
        second = MassiveValuationClient(
            MassiveSettings(api_key="massive_test_key"),
        )

        self.assertIs(first.request_coordinator, second.request_coordinator)

    def test_process_coordinator_is_partitioned_by_credential(self) -> None:
        first = MassiveValuationClient(
            MassiveSettings(api_key="massive_test_key_a"),
        )
        second = MassiveValuationClient(
            MassiveSettings(api_key="massive_test_key_b"),
        )

        self.assertIsNot(first.request_coordinator, second.request_coordinator)

    def test_concurrent_identical_requests_share_one_quota_call(self) -> None:
        transport = DelayedMassiveTransportFake()
        coordinator = MassiveRequestCoordinator(NoopRateLimiter())
        client = MassiveValuationClient(
            MassiveSettings(api_key="massive_test_key"),
            transport=transport,
            request_coordinator=coordinator,
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )
        start = Barrier(3)
        results = []

        def fetch() -> None:
            start.wait()
            results.append(
                client.fetch_daily_close("RXRX", date(2026, 5, 6))
            )

        threads = [Thread(target=fetch), Thread(target=fetch)]
        for thread in threads:
            thread.start()
        start.wait()
        self.assertTrue(transport.entered.wait(timeout=1.0))
        sleep(0.05)
        transport.release.set()
        for thread in threads:
            thread.join(timeout=1.0)

        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])

    def test_fetches_unadjusted_daily_close_without_putting_key_in_url(
        self,
    ) -> None:
        transport = MassiveTransportFake()
        client = MassiveValuationClient(
            MassiveSettings(api_key="massive_test_key"),
            transport=transport,
            rate_limiter=NoopRateLimiter(),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        evidence = client.fetch_daily_close("rxrx", date(2026, 5, 6))

        self.assertEqual(evidence.ticker, "RXRX")
        self.assertEqual(evidence.session_date, date(2026, 5, 6))
        self.assertEqual(evidence.close, "6.25")
        self.assertEqual(evidence.adjustment_status, "split_unadjusted")
        self.assertEqual(evidence.provider, "massive_stocks_basic_candidate")
        self.assertEqual(evidence.contract_status, "candidate_unapproved")
        self.assertEqual(
            evidence.blocking_reason_codes,
            (
                "official_close_provenance_unconfirmed",
                "official_close_timestamp_unavailable",
                "historical_halt_status_unavailable",
                "corporate_action_coverage_incomplete",
                "persistence_rights_unconfirmed",
                "authenticated_display_rights_unconfirmed",
            ),
        )
        self.assertEqual(len(evidence.response_sha256), 64)

        method, url, headers = transport.requests[0]
        self.assertEqual(method, "GET")
        self.assertEqual(
            url,
            "https://api.massive.com/v1/open-close/RXRX/2026-05-06"
            "?adjusted=false",
        )
        self.assertEqual(
            headers["Authorization"],
            "Bearer massive_test_key",
        )
        self.assertNotIn("massive_test_key", url)
        self.assertNotIn("massive_test_key", evidence.source_reference)

    def test_never_sends_more_than_five_requests_in_rolling_minute(self) -> None:
        monotonic_time = [0.0]

        def monotonic() -> float:
            return monotonic_time[0]

        def sleep(seconds: float) -> None:
            monotonic_time[0] += seconds

        transport = RateLimitTransportFake(monotonic)
        client = MassiveValuationClient(
            MassiveSettings(api_key="massive_test_key"),
            transport=transport,
            rate_limiter=MassiveRollingRateLimiter(
                max_requests=5,
                window_seconds=60.0,
                clock=monotonic,
                sleeper=sleep,
            ),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        for day in range(1, 7):
            client.fetch_daily_close("RXRX", date(2026, 5, day))

        self.assertEqual(transport.request_times[0], 0.0)
        self.assertTrue(
            all(
                later - earlier >= 13.0
                for earlier, later in zip(
                    transport.request_times,
                    transport.request_times[1:],
                )
            )
        )
        self.assertGreaterEqual(transport.request_times[5], 65.0)

    def test_reuses_successful_identical_request_without_spending_quota(
        self,
    ) -> None:
        monotonic_time = [0.0]
        transport = MassiveTransportFake()
        client = MassiveValuationClient(
            MassiveSettings(api_key="massive_test_key"),
            transport=transport,
            rate_limiter=MassiveRollingRateLimiter(
                clock=lambda: monotonic_time[0],
                sleeper=lambda seconds: monotonic_time.__setitem__(
                    0,
                    monotonic_time[0] + seconds,
                ),
            ),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        first = client.fetch_daily_close("RXRX", date(2026, 5, 6))
        second = client.fetch_daily_close("rxrx", date(2026, 5, 6))

        self.assertEqual(first, second)
        self.assertEqual(len(transport.requests), 1)

    def test_429_surfaces_retry_after_without_hidden_retry(self) -> None:
        transport = QuotaResponseFake()
        client = MassiveValuationClient(
            MassiveSettings(api_key="massive_test_key"),
            transport=transport,
            rate_limiter=NoopRateLimiter(),
        )

        with self.assertRaises(MassiveRateLimitError) as caught:
            client.fetch_daily_close("RXRX", date(2026, 5, 6))

        self.assertEqual(caught.exception.retry_after_seconds, 47)
        self.assertEqual(transport.request_count, 1)

    def test_429_blocks_follow_up_request_for_shared_retry_window(self) -> None:
        transport = QuotaResponseFake()
        coordinator = MassiveRequestCoordinator(NoopRateLimiter())
        client = MassiveValuationClient(
            MassiveSettings(api_key="massive_test_key"),
            transport=transport,
            request_coordinator=coordinator,
            cache_clock=lambda: 0.0,
        )

        with self.assertRaises(MassiveRateLimitError):
            client.fetch_daily_close("RXRX", date(2026, 5, 6))
        with self.assertRaises(MassiveRateLimitError) as caught:
            client.fetch_daily_close("RXRX", date(2026, 5, 7))

        self.assertEqual(caught.exception.retry_after_seconds, 47)
        self.assertEqual(transport.request_count, 1)

    def test_429_parses_http_date_retry_after_conservatively(self) -> None:
        transport = QuotaResponseFake(
            retry_after="Thu, 23 Jul 2026 12:02:00 GMT"
        )
        client = MassiveValuationClient(
            MassiveSettings(api_key="massive_http_date_key"),
            transport=transport,
            rate_limiter=NoopRateLimiter(),
            clock=lambda: datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
        )

        with self.assertRaises(MassiveRateLimitError) as caught:
            client.fetch_daily_close("RXRX", date(2026, 5, 6))

        self.assertEqual(caught.exception.retry_after_seconds, 120)
        self.assertEqual(transport.request_count, 1)


if __name__ == "__main__":
    unittest.main()
