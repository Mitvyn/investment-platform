from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess
from typing import Mapping
from unittest.mock import patch

from workers.issuer.__main__ import RXRX_Q1_2026
from workers.issuer.collector import (
    BytesResponse,
    CurlBytesTransport,
    IssuerCollector,
    IssuerCollectorError,
)
from workers.issuer.tracer import build_issuer_context


class FakeTransport:
    def __init__(self, response: BytesResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> BytesResponse:
        self.calls.append((url, headers))
        return self.response


class IssuerCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.body = Path(
            "tests/fixtures/issuer/rxrx-q1-2026.html"
        ).read_bytes()
        self.transport = FakeTransport(
            BytesResponse(body=self.body, status=200, headers={})
        )
        self.collector = IssuerCollector(
            transport=self.transport,
            clock=lambda: datetime(2026, 7, 17, 2, 30, tzinfo=UTC),
        )

    def test_collects_only_canonical_url_without_overriding_transport_user_agent(
        self,
    ) -> None:
        release = self.collector.fetch_release(RXRX_Q1_2026)

        self.assertEqual(self.transport.calls[0][0], RXRX_Q1_2026.source_url)
        self.assertNotIn("User-Agent", self.transport.calls[0][1])
        self.assertEqual(release.retrieved_at, "2026-07-17T02:30:00+00:00")

    @patch("workers.issuer.collector.subprocess.run")
    def test_curl_transport_keeps_native_user_agent_and_parses_status(
        self,
        run,
    ) -> None:
        run.return_value = CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"<html>release</html>\n__IROS_HTTP_STATUS__:200",
            stderr=b"",
        )

        response = CurlBytesTransport(5).request(
            RXRX_Q1_2026.source_url,
            headers={"Accept": "text/html,application/xhtml+xml"},
        )

        command = run.call_args.args[0]
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, b"<html>release</html>")
        self.assertNotIn("--user-agent", command)
        self.assertFalse(any("User-Agent:" in value for value in command))

    @patch("workers.issuer.collector.subprocess.run")
    def test_curl_transport_reports_timeout_without_traceback(self, run) -> None:
        run.return_value = CompletedProcess(
            args=[],
            returncode=28,
            stdout=b"",
            stderr=b"curl: (28) Operation timed out",
        )

        with self.assertRaisesRegex(IssuerCollectorError, "timed out"):
            CurlBytesTransport(5).request(
                RXRX_Q1_2026.source_url,
                headers={"Accept": "text/html,application/xhtml+xml"},
            )
        self.assertEqual(run.call_count, 2)

    def test_maps_exact_passages_and_deterministic_calculations(self) -> None:
        collected = self.collector.fetch_release(RXRX_Q1_2026)
        context = build_issuer_context(
            collected,
            operator_id="11111111-1111-4111-8111-111111111111",
        )

        self.assertEqual(len(context.passages), 4)
        metrics = {metric.metric_key: metric for metric in context.metrics}
        self.assertEqual(metrics["cash_and_restricted_cash"].value, 665.2)
        self.assertEqual(metrics["simple_runway_quarters"].value, 8.2)
        self.assertEqual(metrics["cash_change_percent"].value, -11.77)
        self.assertEqual(
            metrics["operating_cash_use_improvement_percent"].value,
            38.56,
        )
        self.assertIn("$665.2m / $81.1m", metrics["simple_runway_quarters"].formula or "")
        self.assertEqual(context.catalysts[0].window_end, "2026-12-31")
        self.assertEqual(context.risks[0].risk_type, "financial")
        self.assertEqual(context.risks[0].severity, "medium")

    def test_dynamic_page_wrapper_does_not_change_evidence_content_hash(
        self,
    ) -> None:
        collected = self.collector.fetch_release(RXRX_Q1_2026)
        changed_wrapper = collected.__class__(
            request=collected.request,
            retrieved_at=collected.retrieved_at,
            html=collected.html.replace(
                "<body>",
                "<body><script>dynamic-token-2</script>",
            ),
            content_sha256="0" * 64,
        )

        first = build_issuer_context(
            collected,
            operator_id="11111111-1111-4111-8111-111111111111",
        )
        second = build_issuer_context(
            changed_wrapper,
            operator_id="11111111-1111-4111-8111-111111111111",
        )

        self.assertEqual(first.content_sha256, second.content_sha256)

    def test_rejects_non_success_response(self) -> None:
        collector = IssuerCollector(
            transport=FakeTransport(
                BytesResponse(body=b"unavailable", status=503, headers={})
            )
        )

        with self.assertRaisesRegex(IssuerCollectorError, "HTTP 503"):
            collector.fetch_release(RXRX_Q1_2026)

    def test_rejects_missing_exact_passage(self) -> None:
        release = self.collector.fetch_release(RXRX_Q1_2026)
        broken = release.__class__(
            request=release.request,
            retrieved_at=release.retrieved_at,
            html=release.html.replace("$665.2 million", "$0.0 million"),
            content_sha256=release.content_sha256,
        )

        with self.assertRaisesRegex(ValueError, "cash.*exactly once"):
            build_issuer_context(
                broken,
                operator_id="11111111-1111-4111-8111-111111111111",
            )


if __name__ == "__main__":
    unittest.main()
