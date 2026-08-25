from __future__ import annotations

import json
import unittest
from typing import Mapping
from urllib.error import HTTPError

from workers.moomoo_mcp.http_client import MoomooMcpError, MoomooMcpHttpClient


class FakeResponse:
    def __init__(self, payload: bytes, *, headers: Mapping[str, str] | None = None) -> None:
        self._payload = payload
        self.headers = dict(headers or {})
        self.status = 200
        self.code = 200

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return "https://mcp.moomoo.com/mcp"

    def read(self, _limit: int) -> bytes:
        return self._payload


class FakeOpener:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests = []

    def __call__(self, request: object, *, timeout: float, context: object) -> FakeResponse:
        self.requests.append((request, timeout, context))
        return self.responses.pop(0)


class HttpErrorOpener:
    def __call__(self, request: object, *, timeout: float, context: object) -> object:
        del timeout, context
        raise HTTPError(request.full_url, 400, "provider detail", {}, None)


def response(
    result: Mapping[str, object],
    *,
    message_id: int,
    session_id: str | None = None,
) -> FakeResponse:
    headers = {"Content-Type": "application/json"}
    if session_id is not None:
        headers["Mcp-Session-Id"] = session_id
    return FakeResponse(
        json.dumps({"jsonrpc": "2.0", "id": message_id, "result": result}).encode(),
        headers=headers,
    )


class MoomooMcpHttpClientTests(unittest.TestCase):
    def test_jsonrpc_failure_exposes_only_a_bounded_reason_code(self) -> None:
        opener = FakeOpener(
            [
                response(
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "Moomoo", "version": "test"},
                    },
                    message_id=1,
                    session_id="session-1",
                ),
                FakeResponse(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "error": {
                                "code": -32602,
                                "message": "secret provider detail",
                            },
                        }
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                ),
            ]
        )
        client = MoomooMcpHttpClient(access_token="access-secret", opener=opener)

        with self.assertRaises(MoomooMcpError) as context:
            client.call_tool("quote_stock_quote", {"code_list": ["US.AAPL"]})

        self.assertEqual(context.exception.code, "jsonrpc_invalid_params")
        self.assertNotIn("secret provider detail", str(context.exception))

    def test_http_failure_exposes_status_without_provider_detail(self) -> None:
        client = MoomooMcpHttpClient(
            access_token="access-secret", opener=HttpErrorOpener()
        )

        with self.assertRaises(MoomooMcpError) as context:
            client.call_tool("quote_stock_quote", {"code_list": ["US.AAPL"]})

        self.assertEqual(context.exception.code, "http_400")
        self.assertNotIn("provider detail", str(context.exception))

    def test_list_tools_initializes_session_and_never_exposes_bearer(self) -> None:
        opener = FakeOpener(
            [
                response(
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "Moomoo", "version": "test"},
                    },
                    message_id=1,
                    session_id="session-1",
                ),
                FakeResponse(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "result": {
                                "tools": [
                                    {
                                        "name": "quote_stock_quote",
                                        "description": "Quote read",
                                        "inputSchema": {"type": "object"},
                                    }
                                ]
                            },
                        }
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                ),
            ]
        )

        client = MoomooMcpHttpClient(
            access_token="access-secret",
            opener=opener,
        )
        tools = client.list_tools()

        self.assertEqual(tools[0]["name"], "quote_stock_quote")
        self.assertEqual(len(opener.requests), 2)
        first_request = opener.requests[0][0]
        second_request = opener.requests[1][0]
        self.assertEqual(first_request.method, "POST")
        self.assertEqual(first_request.get_header("Authorization"), "Bearer access-secret")
        self.assertEqual(second_request.get_header("Mcp-session-id"), "session-1")
        self.assertNotIn("access-secret", repr(client))

    def test_call_tool_initializes_session_then_sends_tools_call(self) -> None:
        opener = FakeOpener(
            [
                response(
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "Moomoo", "version": "test"},
                    },
                    message_id=1,
                    session_id="session-1",
                ),
                response(
                    {
                        "isError": False,
                        "structuredContent": {"code": "US.AAPL", "time": 1_700_000_000},
                    },
                    message_id=2,
                ),
            ]
        )
        client = MoomooMcpHttpClient(access_token="access-secret", opener=opener)

        result = client.call_tool("quote_stock_quote", {"code_list": ["US.AAPL"]})

        self.assertEqual(result["structuredContent"]["code"], "US.AAPL")
        self.assertEqual(len(opener.requests), 2)
        second_body = json.loads(opener.requests[1][0].data)
        self.assertEqual(second_body["method"], "tools/call")
        self.assertEqual(second_body["params"]["name"], "quote_stock_quote")
        self.assertEqual(second_body["params"]["arguments"], {"code_list": ["US.AAPL"]})
        self.assertNotIn("access-secret", repr(client))

    def test_call_tool_promotes_one_json_text_result_to_structured_content(self) -> None:
        opener = FakeOpener(
            [
                response(
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "Moomoo", "version": "test"},
                    },
                    message_id=1,
                    session_id="session-1",
                ),
                response(
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": '{"quote_list":[{"code":"US.FRVO"}]}',
                            }
                        ],
                        "isError": False,
                    },
                    message_id=2,
                ),
            ]
        )

        result = MoomooMcpHttpClient(
            access_token="access-secret", opener=opener
        ).call_tool("quote_stock_quote", {"code_list": ["US.FRVO"]})

        self.assertEqual(
            result["structuredContent"],
            {"quote_list": [{"code": "US.FRVO"}]},
        )

    def test_call_tool_treats_empty_structured_content_as_absent(self) -> None:
        opener = FakeOpener(
            [
                response(
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "Moomoo", "version": "test"},
                    },
                    message_id=1,
                    session_id="session-1",
                ),
                response(
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": '{"quote_list":[{"code":"US.FRVO"}]}',
                            }
                        ],
                        "isError": False,
                        "structuredContent": {},
                    },
                    message_id=2,
                ),
            ]
        )

        result = MoomooMcpHttpClient(
            access_token="access-secret", opener=opener
        ).call_tool("quote_stock_quote", {"code_list": ["US.FRVO"]})

        self.assertEqual(
            result["structuredContent"],
            {"quote_list": [{"code": "US.FRVO"}]},
        )

    def test_call_tool_unwraps_exact_successful_provider_rest_envelope(self) -> None:
        opener = FakeOpener(
            [
                response(
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "Moomoo", "version": "test"},
                    },
                    message_id=1,
                    session_id="session-1",
                ),
                response(
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "ret_code": 0,
                                        "ret_msg": "success",
                                        "data": {
                                            "quote_list": [{"code": "US.FRVO"}]
                                        },
                                    }
                                ),
                            }
                        ],
                        "isError": False,
                    },
                    message_id=2,
                ),
            ]
        )

        result = MoomooMcpHttpClient(
            access_token="access-secret", opener=opener
        ).call_tool("quote_stock_quote", {"code_list": ["US.FRVO"]})

        self.assertEqual(
            result["structuredContent"],
            {"quote_list": [{"code": "US.FRVO"}]},
        )

    def test_call_tool_unwraps_documented_moomoo_s_d_envelope(self) -> None:
        opener = FakeOpener(
            [
                response(
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "Moomoo", "version": "test"},
                    },
                    message_id=1,
                    session_id="session-1",
                ),
                response(
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "s": "ok",
                                        "d": {
                                            "quote_list": [{"code": "US.FRVO"}]
                                        },
                                    }
                                ),
                            }
                        ],
                        "isError": False,
                    },
                    message_id=2,
                ),
            ]
        )

        result = MoomooMcpHttpClient(
            access_token="access-secret", opener=opener
        ).call_tool("quote_stock_quote", {"code_list": ["US.FRVO"]})

        self.assertEqual(
            result["structuredContent"],
            {"quote_list": [{"code": "US.FRVO"}]},
        )

    def test_call_tool_rejects_ambiguous_or_non_json_text_fallback(self) -> None:
        invalid_content_sets = (
            [{"type": "text", "text": "not json"}],
            [
                {"type": "text", "text": '{"quote_list":[]}'},
                {"type": "text", "text": '{"quote_list":[]}'},
            ],
            [{"type": "image", "data": "ignored", "mimeType": "image/png"}],
        )
        for content in invalid_content_sets:
            with self.subTest(content=content):
                opener = FakeOpener(
                    [
                        response(
                            {
                                "protocolVersion": "2025-06-18",
                                "capabilities": {"tools": {}},
                                "serverInfo": {"name": "Moomoo", "version": "test"},
                            },
                            message_id=1,
                            session_id="session-1",
                        ),
                        response(
                            {"content": content, "isError": False},
                            message_id=2,
                        ),
                    ]
                )
                with self.assertRaises(MoomooMcpError):
                    MoomooMcpHttpClient(
                        access_token="access-secret", opener=opener
                    ).call_tool(
                        "quote_stock_quote", {"code_list": ["US.FRVO"]}
                    )

    def test_call_tool_rejects_blank_tool_name(self) -> None:
        client = MoomooMcpHttpClient(access_token="access-secret", opener=FakeOpener([]))
        with self.assertRaises(MoomooMcpError):
            client.call_tool("", {})

    def test_call_tool_rejects_invalid_result_shape(self) -> None:
        opener = FakeOpener(
            [
                response(
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "Moomoo", "version": "test"},
                    },
                    message_id=1,
                    session_id="session-1",
                ),
                response({"structuredContent": {}}, message_id=2),
            ]
        )
        client = MoomooMcpHttpClient(access_token="access-secret", opener=opener)
        with self.assertRaises(MoomooMcpError):
            client.call_tool("quote_stock_quote", {"code_list": ["US.AAPL"]})


if __name__ == "__main__":
    unittest.main()
