from __future__ import annotations

import unittest

from workers.primary_sources.acquisition import SpacedBytesTransport
from workers.primary_sources.http import (
    CurlCffiBytesTransport,
    PrimarySourceHttpError,
)
from workers.sec.collector import BytesResponse


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 10.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class RecordingTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []

    def request(self, url: str, *, headers):
        self.requests.append((url, dict(headers)))
        return BytesResponse(
            body=b"{}",
            status=200,
            headers={"Content-Type": "application/json"},
            final_url=url,
        )


class FakeResponse:
    content = b'{"ok":true}'
    status_code = 200
    headers = {"Content-Type": "application/json"}
    url = "https://clinicaltrials.gov/final"


class FakeSession:
    def __init__(self, *, error=None) -> None:
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return FakeResponse()


class CurlCffiBytesTransportTests(unittest.TestCase):
    def test_returns_source_neutral_bytes_response(self) -> None:
        session = FakeSession()
        transport = CurlCffiBytesTransport(
            timeout_seconds=17,
            session=session,
        )

        response = transport.request(
            "https://clinicaltrials.gov/source",
            headers={"Accept": "application/json"},
        )

        self.assertEqual(response.body, b'{"ok":true}')
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.final_url,
            "https://clinicaltrials.gov/final",
        )
        self.assertEqual(
            session.calls,
            [
                (
                    "https://clinicaltrials.gov/source",
                    {
                        "headers": {"Accept": "application/json"},
                        "timeout": 17,
                        "allow_redirects": True,
                    },
                )
            ],
        )

    def test_wraps_request_failure_without_mislabeling_source(self) -> None:
        from curl_cffi import requests

        transport = CurlCffiBytesTransport(
            timeout_seconds=17,
            session=FakeSession(
                error=requests.RequestsError("unavailable")
            ),
        )

        with self.assertRaisesRegex(
            PrimarySourceHttpError,
            "primary source request failed",
        ):
            transport.request(
                "https://clinicaltrials.gov/source",
                headers={"Accept": "application/json"},
            )


class SpacedBytesTransportTests(unittest.TestCase):
    def test_serializes_requests_with_contact_header_and_spacing(
        self,
    ) -> None:
        clock = FakeMonotonic()
        delegate = RecordingTransport()
        transport = SpacedBytesTransport(
            delegate,
            user_agent="Investment Research OS operator@example.com",
            minimum_interval_seconds=0.5,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

        transport.request(
            "https://data.sec.gov/one",
            headers={"Accept": "application/json"},
        )
        transport.request(
            "https://data.sec.gov/two",
            headers={"Accept": "application/json"},
        )

        self.assertEqual(clock.sleeps, [0.5])
        self.assertEqual(
            delegate.requests,
            [
                (
                    "https://data.sec.gov/one",
                    {
                        "Accept": "application/json",
                        "User-Agent": (
                            "Investment Research OS "
                            "operator@example.com"
                        ),
                    },
                ),
                (
                    "https://data.sec.gov/two",
                    {
                        "Accept": "application/json",
                        "User-Agent": (
                            "Investment Research OS "
                            "operator@example.com"
                        ),
                    },
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
