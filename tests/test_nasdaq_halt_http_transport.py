from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime

from investment_research_os.valuation_snapshots.nasdaq_halt_http import (
    NasdaqTraderHaltHttpSettings,
    NasdaqTraderHaltHttpTransport,
)
from investment_research_os.valuation_snapshots.market_proofs import (
    NasdaqTraderHistoricalHaltVerifier,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_massive_personal_research_adapter import daily_close
from tests.test_valuation_snapshot_workflow import SESSION


SOURCE_URL = "https://www.nasdaqtrader.com/Trader.aspx?id=TradingHaltSearch"
RPC_URL = "https://www.nasdaqtrader.com/RPCHandler.axd"


class FakeHttpResponse:
    def __init__(
        self,
        body: bytes,
        *,
        url: str,
        content_type: str,
    ) -> None:
        self._body = body
        self._url = url
        self.status = 200
        self.headers = {"Content-Type": content_type}

    def read(self, amount: int = -1) -> bytes:
        return self._body if amount < 0 else self._body[:amount]

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class RecordingExecutor:
    def __init__(self, responses: tuple[FakeHttpResponse, ...]) -> None:
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, *, timeout, context):
        self.requests.append((request, timeout, context))
        return self.responses.pop(0)


class RaisingExecutor:
    def __call__(self, request, *, timeout, context):
        raise TimeoutError("timed out")


def halt_search_page() -> bytes:
    return b"""
    <html><head><title>Trading Halt Search</title>
      <script src="rpcclient.axd"></script>
    </head><body>
      <input type="text" id="txtSymbol" name="txtSymbol" />
      <input type="text" id="txtDateStart" name="txtDateStart" />
      <input type="text" id="txtDateStartTo" name="txtDateStartTo" />
      <script>
        Server.BL_TradeHalt.SearchTradeHaltsNEW(
          callback, symbol, reason, market, start, end, resume, resumeEnd
        );
      </script>
    </body></html>
    """


def rpc_response(result: str, *, request_id: str = "1") -> bytes:
    return json.dumps(
        {"result": result, "id": request_id, "version": "1.1"},
        separators=(",", ":"),
    ).encode()


def halt_result_table(*, rows: str = "") -> str:
    return f"""
    <div class="genTable"><table>
      <tr>
        <th>Halt Date</th><th>Halt Time</th><th>Issue Symbol</th>
        <th>Issue Name</th><th>Market</th><th>Reason Code</th>
        <th>Pause Threshold Price</th><th>Resumption Date</th>
        <th>Resumption Quote Time</th><th>Resumption Trade Time</th>
      </tr>
      {rows}
    </table></div>
    """


def html_response(body: bytes) -> FakeHttpResponse:
    return FakeHttpResponse(
        body,
        url=SOURCE_URL,
        content_type="text/html; charset=utf-8",
    )


def json_response(body: bytes) -> FakeHttpResponse:
    return FakeHttpResponse(
        body,
        url=RPC_URL,
        content_type="application/json; charset=utf-8",
    )


class NasdaqTraderHaltHttpTransportTests(unittest.TestCase):
    def test_search_submits_bound_rpc_query_and_maps_complete_empty_result(
        self,
    ) -> None:
        executor = RecordingExecutor(
            (
                html_response(halt_search_page()),
                json_response(rpc_response("No Data Found")),
            )
        )
        transport = NasdaqTraderHaltHttpTransport(
            NasdaqTraderHaltHttpSettings(
                user_agent="Investment Research OS operator@example.com",
                timeout_seconds=9,
            ),
            request_executor=executor,
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        result = transport.search_halts(
            symbol="RXRX",
            session_date=date(2026, 5, 6),
        )

        self.assertTrue(result.complete)
        self.assertEqual(result.query_symbol, "RXRX")
        self.assertEqual(result.query_session_date, date(2026, 5, 6))
        self.assertEqual(result.records, ())
        self.assertEqual(result.source_locator, SOURCE_URL)
        self.assertEqual(result.retrieved_at, datetime(2026, 5, 7, 1, 0, tzinfo=UTC))
        self.assertEqual(len(result.response_sha256), 64)
        self.assertEqual(len(executor.requests), 2)
        bootstrap, search = executor.requests
        self.assertEqual(bootstrap[0].get_method(), "GET")
        self.assertEqual(search[0].get_method(), "POST")
        self.assertEqual(bootstrap[0].full_url, SOURCE_URL)
        self.assertEqual(search[0].full_url, RPC_URL)
        self.assertEqual(bootstrap[1], 9)
        self.assertEqual(search[1], 9)
        self.assertEqual(
            bootstrap[0].get_header("User-agent"),
            "Investment Research OS operator@example.com",
        )
        self.assertEqual(search[0].get_header("Content-type"), "application/json")
        self.assertEqual(search[0].get_header("Referer"), SOURCE_URL)
        self.assertEqual(
            json.loads(search[0].data),
            {
                "id": 1,
                "method": "BL_TradeHalt.SearchTradeHaltsNEW",
                "params": [
                    "RXRX",
                    "",
                    "",
                    "05/06/2026",
                    "05/06/2026",
                    "",
                    "",
                ],
                "version": "1.1",
            },
        )

    def test_search_maps_live_table_shape_for_verifier_contract(self) -> None:
        row = """
        <tr>
          <td>05/06/2026</td><td>15:30:00.000</td><td>RXRX</td>
          <td>Recursion Pharmaceuticals, Inc.</td><td>NASDAQ</td><td>T1</td>
          <td></td><td>05/06/2026</td><td>16:29:00.000</td>
          <td>16:30:00.000</td>
        </tr>
        """
        executor = RecordingExecutor(
            (
                html_response(halt_search_page()),
                json_response(rpc_response(halt_result_table(rows=row))),
            )
        )
        transport = NasdaqTraderHaltHttpTransport(
            NasdaqTraderHaltHttpSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            request_executor=executor,
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        result = transport.search_halts(
            symbol="RXRX",
            session_date=date(2026, 5, 6),
        )

        self.assertEqual(len(result.records), 1)
        self.assertEqual(
            result.records[0],
            {
                "record_id": result.records[0]["record_id"],
                "symbol": "RXRX",
                "market": "NASDAQ",
                "halted_at": "2026-05-06T15:30:00-04:00",
                "resumed_at": "2026-05-06T16:30:00-04:00",
                "reason_code": "T1",
            },
        )
        self.assertEqual(len(str(result.records[0]["record_id"])), 64)

    def test_response_id_mismatch_fails_closed(self) -> None:
        executor = RecordingExecutor(
            (
                html_response(halt_search_page()),
                json_response(rpc_response("No Data Found", request_id="other")),
            )
        )
        transport = NasdaqTraderHaltHttpTransport(
            NasdaqTraderHaltHttpSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            request_executor=executor,
        )

        with self.assertRaisesRegex(RuntimeError, "response envelope is invalid"):
            transport.search_halts(
                symbol="RXRX",
                session_date=date(2026, 5, 6),
            )

    def test_live_table_schema_drift_fails_closed(self) -> None:
        drifted_table = halt_result_table().replace(
            "<th>Resumption Trade Time</th>",
            "<th>Resumption Trade Time</th><th>Unexpected Field</th>",
        )
        executor = RecordingExecutor(
            (
                html_response(halt_search_page()),
                json_response(rpc_response(drifted_table)),
            )
        )
        transport = NasdaqTraderHaltHttpTransport(
            NasdaqTraderHaltHttpSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            request_executor=executor,
        )

        with self.assertRaisesRegex(RuntimeError, "result table is unsupported"):
            transport.search_halts(
                symbol="RXRX",
                session_date=date(2026, 5, 6),
            )

    def test_verifier_treats_transport_timeout_as_indeterminate(self) -> None:
        transport = NasdaqTraderHaltHttpTransport(
            NasdaqTraderHaltHttpSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            request_executor=RaisingExecutor(),
        )
        verifier = NasdaqTraderHistoricalHaltVerifier(
            transport=transport,
            source_version="nasdaq-trader-halt-search.v2",
            coverage_start=date(2026, 1, 1),
            coverage_end=date(2026, 12, 31),
        )

        status = verifier.verify(materialized_bundle(), SESSION, daily_close())

        self.assertEqual(status, "indeterminate")


if __name__ == "__main__":
    unittest.main()
