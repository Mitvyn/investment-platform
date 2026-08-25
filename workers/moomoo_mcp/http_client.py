"""HTTP client for Moomoo's MCP Streamable HTTP endpoint.

This module owns two narrow capabilities: authenticated ``initialize``
followed by ``tools/list`` (discovery), and a single ``tools/call`` dispatch
by exact tool name (``call_tool``). It performs no tool-name allowlisting of
its own — callers are responsible for validating a tool name against an
authenticated discovery manifest and a read-only policy before calling
``call_tool``. Access tokens must come from a separate MCP OAuth boundary,
are used in memory for the request, and never returned in a response or
representation. The OpenAPI connection token is not a valid substitute at
this boundary.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from workers.http import trusted_ssl_context


MOOMOO_MCP_ENDPOINT = "https://mcp.moomoo.com/mcp"
MCP_PROTOCOL_VERSION = "2025-06-18"
MAX_RESPONSE_BYTES = 1_048_576


class MoomooMcpError(RuntimeError):
    """Raised when MCP discovery cannot produce a trusted manifest."""

    def __init__(self, message: str, *, code: str = "request_failed") -> None:
        super().__init__(message)
        self.code = code


class MoomooMcpHttpClient:
    """Authenticated Moomoo MCP client for discovery and one-tool-at-a-time calls.

    Exposes `list_tools()` (discovery) and `call_tool()` (a single `tools/call`
    dispatch by exact name). It has no allowlisting of its own — callers must
    validate a tool name against an authenticated discovery manifest and a
    read-only policy before calling `call_tool`.
    """

    def __init__(
        self,
        *,
        access_token: str,
        opener: Callable[..., object] = urlopen,
        endpoint: str = MOOMOO_MCP_ENDPOINT,
        timeout_seconds: float = 15,
    ) -> None:
        if not isinstance(access_token, str) or not access_token.strip():
            raise ValueError("Moomoo MCP access token is required")
        if endpoint != MOOMOO_MCP_ENDPOINT:
            raise ValueError("Moomoo MCP endpoint is not approved")
        if timeout_seconds <= 0:
            raise ValueError("Moomoo MCP timeout must be positive")
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or parsed.netloc != "mcp.moomoo.com":
            raise ValueError("Moomoo MCP endpoint must use the official HTTPS host")
        self._access_token = access_token
        self._opener = opener
        self._timeout_seconds = timeout_seconds
        self._ssl_context = trusted_ssl_context()
        self._session_id: str | None = None

    def __repr__(self) -> str:
        return "MoomooMcpHttpClient(<redacted>)"

    def list_tools(self) -> list[Mapping[str, object]]:
        """Initialize one session and return only its advertised tool rows."""

        self._request(
            message_id=1,
            method="initialize",
            params={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "Investment Research OS",
                    "version": "mcp-discovery-1",
                },
            },
        )
        result = self._request(message_id=2, method="tools/list", params={})
        tools = result.get("tools")
        if not isinstance(tools, list) or any(
            not isinstance(tool, Mapping) for tool in tools
        ):
            raise MoomooMcpError("Moomoo MCP tools/list result is invalid")
        return [dict(tool) for tool in tools]

    def call_tool(
        self, name: str, arguments: Mapping[str, object]
    ) -> Mapping[str, object]:
        """Invoke exactly one already-approved MCP tool by name.

        Callers are responsible for allowlisting ``name`` against an
        authenticated discovery manifest before calling this method; this
        client performs no tool-name policy of its own beyond structural
        validation.
        """

        if not isinstance(name, str) or not name.strip():
            raise MoomooMcpError("Moomoo MCP tool name is invalid")
        if not isinstance(arguments, Mapping):
            raise MoomooMcpError("Moomoo MCP tool arguments are invalid")
        if self._session_id is None:
            self._request(
                message_id=1,
                method="initialize",
                params={
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "Investment Research OS",
                        "version": "mcp-discovery-1",
                    },
                },
            )
        result = self._request(
            message_id=2,
            method="tools/call",
            params={"name": name.strip(), "arguments": dict(arguments)},
        )
        is_error = result.get("isError", False)
        if not isinstance(is_error, bool):
            raise MoomooMcpError("Moomoo MCP tool result isError flag is invalid")
        structured = result.get("structuredContent")
        content = result.get("content")
        if structured is not None and not isinstance(structured, Mapping):
            raise MoomooMcpError("Moomoo MCP tool result is invalid")
        if isinstance(structured, Mapping) and not structured:
            structured = None
        if structured is None and content is None:
            raise MoomooMcpError("Moomoo MCP tool result is invalid")
        if content is not None and (
            not isinstance(content, list)
            or not content
            or any(not isinstance(item, Mapping) for item in content)
        ):
            raise MoomooMcpError("Moomoo MCP tool result is invalid")
        normalized_result = dict(result)
        if not is_error and structured is None:
            structured = _json_text_content(content)
        if not is_error and structured is not None:
            normalized_result["structuredContent"] = _unwrap_provider_rest_envelope(
                structured
            )
        return normalized_result

    def _request(
        self,
        *,
        message_id: int,
        method: str,
        params: Mapping[str, object],
    ) -> Mapping[str, object]:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": message_id,
                "method": method,
                "params": dict(params),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        request = Request(
            MOOMOO_MCP_ENDPOINT,
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with self._opener(
                request,
                timeout=self._timeout_seconds,
                context=self._ssl_context,
            ) as response:
                response_url = getattr(response, "geturl", None)
                if callable(response_url) and response_url() != MOOMOO_MCP_ENDPOINT:
                    raise MoomooMcpError("Moomoo MCP redirect is not allowed")
                status = int(getattr(response, "status", getattr(response, "code", 0)))
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                raw_headers = getattr(response, "headers", {})
                response_headers = dict(raw_headers.items()) if hasattr(raw_headers, "items") else {}
        except MoomooMcpError:
            raise
        except HTTPError as error:
            raise MoomooMcpError(
                f"Moomoo MCP HTTP status {error.code}",
                code=f"http_{error.code}",
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise MoomooMcpError("Moomoo MCP request failed") from error
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MoomooMcpError("Moomoo MCP response is too large")
        if status < 200 or status >= 300:
            raise MoomooMcpError(f"Moomoo MCP HTTP status {status}")
        for key, value in response_headers.items():
            if key.lower() == "mcp-session-id":
                if not isinstance(value, str) or not value.strip():
                    raise MoomooMcpError("Moomoo MCP session header is invalid")
                self._session_id = value.strip()
                break
        message = _decode_message(raw, response_headers)
        if message.get("jsonrpc") != "2.0" or message.get("id") != message_id:
            raise MoomooMcpError("Moomoo MCP JSON-RPC response is invalid")
        error = message.get("error")
        if error is not None:
            raise MoomooMcpError(
                "Moomoo MCP JSON-RPC request failed",
                code=_jsonrpc_error_code(error),
            )
        result = message.get("result")
        if not isinstance(result, Mapping):
            raise MoomooMcpError("Moomoo MCP JSON-RPC result is invalid")
        return result


def _decode_message(raw: bytes, headers: Mapping[str, str]) -> Mapping[str, object]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MoomooMcpError("Moomoo MCP response is not UTF-8") from error
    content_type = next(
        (
            value.lower()
            for key, value in headers.items()
            if key.lower() == "content-type" and isinstance(value, str)
        ),
        "",
    )
    if "text/event-stream" in content_type:
        data_lines: list[str] = []
        for line in text.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        text = "\n".join(data_lines)
    try:
        message = json.loads(text)
    except json.JSONDecodeError as error:
        raise MoomooMcpError("Moomoo MCP response is invalid JSON") from error
    if not isinstance(message, Mapping):
        raise MoomooMcpError("Moomoo MCP response is invalid")
    return message


def _jsonrpc_error_code(error: object) -> str:
    if not isinstance(error, Mapping):
        return "jsonrpc_error"
    code = error.get("code")
    return {
        -32700: "jsonrpc_parse_error",
        -32600: "jsonrpc_invalid_request",
        -32601: "jsonrpc_method_not_found",
        -32602: "jsonrpc_invalid_params",
        -32603: "jsonrpc_internal_error",
    }.get(code, "jsonrpc_provider_error")


def _json_text_content(content: object) -> Mapping[str, object]:
    """Recover protocol-valid structured data from one JSON TextContent block.

    MCP 2025-06-18 makes ``structuredContent`` optional and permits structured
    results to be serialized in ``content`` for compatibility. Keep fallback
    narrow: exactly one text block containing one non-empty JSON object.
    """

    if not isinstance(content, list) or len(content) != 1:
        raise MoomooMcpError("Moomoo MCP tool text result is ambiguous")
    item = content[0]
    if not isinstance(item, Mapping) or item.get("type") != "text":
        raise MoomooMcpError("Moomoo MCP tool text result is invalid")
    text = item.get("text")
    if not isinstance(text, str) or not text.strip():
        raise MoomooMcpError("Moomoo MCP tool text result is invalid")
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as error:
        raise MoomooMcpError("Moomoo MCP tool text result is invalid JSON") from error
    if not isinstance(decoded, Mapping) or not decoded:
        raise MoomooMcpError("Moomoo MCP tool text result is invalid")
    return dict(decoded)


def _unwrap_provider_rest_envelope(
    structured: Mapping[str, object],
) -> Mapping[str, object]:
    """Unwrap Moomoo's documented REST success envelope when MCP preserves it.

    Moomoo's tool catalog documents flattened response ``wrap`` fields, while
    its backing API documents ``s`` / ``d`` plus ``errcode`` / ``errmsg``.
    Some MCP TextContent responses preserve that backing envelope. Keep the
    older exact ``ret_code`` / ``ret_msg`` / ``data`` compatibility form too;
    never broaden arbitrary nested provider payloads.
    """

    if set(structured) == {"s", "d"}:
        if structured.get("s") != "ok":
            raise MoomooMcpError(
                "Moomoo MCP provider reported an error", code="tool_provider_error"
            )
        data = structured.get("d")
        if not isinstance(data, Mapping) or not data:
            raise MoomooMcpError("Moomoo MCP provider data is invalid")
        return dict(data)
    if set(structured) != {"ret_code", "ret_msg", "data"}:
        return dict(structured)
    if structured.get("ret_code") != 0:
        raise MoomooMcpError(
            "Moomoo MCP provider reported an error", code="tool_provider_error"
        )
    data = structured.get("data")
    if not isinstance(data, Mapping) or not data:
        raise MoomooMcpError("Moomoo MCP provider data is invalid")
    return dict(data)


__all__ = ["MOOMOO_MCP_ENDPOINT", "MoomooMcpError", "MoomooMcpHttpClient"]
