from __future__ import annotations

import hashlib
import hmac
import json
import threading
import uuid
import webbrowser
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Mapping, Protocol
from urllib.parse import parse_qs, urlsplit

from workers.portfolio.keychain import MoomooKeychainError, MoomooTokenKeychain
from workers.portfolio.moomoo import (
    READ_ONLY_SCOPES,
    MoomooAccount,
    MoomooPosition,
)
from workers.portfolio.oauth import (
    MoomooOAuthError,
    MoomooOAuthTransport,
    PkceAuthorizationAttempt,
    build_authorization_url,
    create_pkce_attempt,
    exchange_authorization_code,
    refresh_access_token,
)
from workers.portfolio.quote_stream import (
    MoomooQuoteAccess,
    MoomooQuoteProtocolError,
    MoomooQuoteStreamSnapshot,
)
from workers.portfolio.quote_limits import (
    MoomooQuoteLimitError,
    MoomooQuoteSubscriptionBook,
)
from workers.portfolio.snapshot import PortfolioSnapshot, build_portfolio_snapshot
from workers.portfolio.symbols import CanonicalSecurityCandidate
from workers.desktop.research import AcceptedCaptureCatalogEntry, DesktopResearchCaptureCatalog
from workers.desktop.research_capture_import import (
    DesktopCaptureImportError,
    DesktopCaptureImportRequest,
    DesktopCaptureImportService,
)
from workers.desktop.research_notebook import (
    DesktopResearchNotebook,
    TickerNotebookError,
)
from workers.desktop.security_registry import DesktopSecurityRegistry
from workers.quant_workspace.intake import QuantWorkspaceError
from workers.quant_workspace.service import DesktopQuantService
from workers.moomoo_mcp.client_identity import (
    MoomooMcpClientIdentity,
    MoomooMcpClientIdentityStore,
)
from workers.moomoo_mcp.diagnostics import (
    MoomooDiagnosticsLog,
    MoomooResultShape,
    summarize_mcp_result_shape,
)
from workers.moomoo_mcp.http_client import MoomooMcpError, MoomooMcpHttpClient
from workers.moomoo_mcp.keychain import MoomooMcpCredentialError, MoomooMcpTokenKeychain
from workers.moomoo_mcp.oauth import (
    MOOMOO_MCP_RESOURCE,
    MoomooMcpAuthorizationServer,
    MoomooMcpOAuthError,
    MoomooMcpOAuthTransport,
    build_mcp_authorization_url,
    create_pkce_attempt as create_mcp_pkce_attempt,
    exchange_mcp_authorization_code,
    fetch_authorization_server_metadata,
    fetch_protected_resource_metadata,
    refresh_mcp_access_token,
    register_mcp_client,
)
from workers.moomoo_mcp.market_evidence import (
    MARKET_QUOTE_TOOL_NAME,
    TICKER_PATTERN,
    MarketEvidenceError,
    build_market_quote_evidence,
    classify_freshness,
)
from workers.moomoo_mcp.history_evidence import (
    HISTORY_TOOL_NAME,
    HistoryEvidenceError,
    build_daily_history_arguments,
    build_market_history_evidence,
)
from workers.moomoo_mcp.portfolio import (
    ACCOUNT_TOOL_NAME,
    POSITIONS_TOOL_NAME,
    MoomooMcpPortfolioError,
    normalize_mcp_accounts,
    normalize_mcp_positions,
)

READ_ONLY_MARKET_EVIDENCE_TOOLS = frozenset(
    {MARKET_QUOTE_TOOL_NAME, HISTORY_TOOL_NAME}
)


MAX_CONTROL_BODY_BYTES = 8_192


class DesktopControlError(RuntimeError):
    """Raised when a local desktop command violates its bounded contract."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class MoomooConnectionStatus:
    state: str
    account_count: int
    position_count: int
    sync_state: str
    error_code: str | None
    capabilities: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "account_count": self.account_count,
            "capabilities": list(self.capabilities),
            "error_code": self.error_code,
            "position_count": self.position_count,
            "state": self.state,
            "sync_state": self.sync_state,
        }


@dataclass(frozen=True, slots=True)
class MoomooMcpDiscoveryStatus:
    state: str
    tool_count: int
    tools: tuple[Mapping[str, str], ...] = ()
    error_code: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "error_code": self.error_code,
            "state": self.state,
            "tool_count": self.tool_count,
            "tools": [dict(tool) for tool in self.tools],
        }


class MoomooPortfolioClient(Protocol):
    def list_accounts(self) -> tuple[MoomooAccount, ...]: ...

    def list_positions(self, account_id: str) -> tuple[MoomooPosition, ...]: ...


class MoomooMcpDiscoveryClient(Protocol):
    def list_tools(self) -> list[Mapping[str, object]]: ...

    def call_tool(
        self, name: str, arguments: Mapping[str, object]
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class MoomooMarketQuoteStatus:
    state: str
    error_code: str | None = None
    evidence: Mapping[str, object] | None = None
    cached: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "cached": self.cached,
            "error_code": self.error_code,
            "evidence": dict(self.evidence) if self.evidence is not None else None,
            "state": self.state,
        }


class DesktopMoomooQuoteStream(Protocol):
    def start(self, initial_access: MoomooQuoteAccess) -> None: ...

    def replace_symbols(self, symbols: tuple[str, ...]) -> None: ...

    def snapshot(self) -> MoomooQuoteStreamSnapshot: ...

    def stop(self) -> None: ...


@dataclass(frozen=True, slots=True)
class MoomooComposedAccountSnapshot:
    account_label: str
    account_type: str
    security_firm: str
    snapshot: PortfolioSnapshot

    def as_dict(self) -> dict[str, object]:
        return {
            "account_label": self.account_label,
            "account_type": self.account_type,
            "security_firm": self.security_firm,
            "snapshot": self.snapshot.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class MoomooSnapshotComposition:
    snapshots: tuple[MoomooComposedAccountSnapshot, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "snapshot_count": len(self.snapshots),
            "snapshots": [snapshot.as_dict() for snapshot in self.snapshots],
        }


@dataclass(frozen=True, slots=True)
class DesktopSecurityCandidate:
    security_id: str
    ticker: str
    primary_listing_exchange: str


@dataclass(frozen=True, slots=True)
class MoomooHoldingsMirror:
    accounts: tuple[MoomooAccount, ...]
    positions: tuple[MoomooPosition, ...]
    sync_state: str

    def as_dict(self) -> dict[str, object]:
        account_indexes = {
            account.account_id: index
            for index, account in enumerate(self.accounts, start=1)
        }
        return {
            "account_count": len(self.accounts),
            "position_count": len(self.positions),
            "positions": [
                {
                    "account_index": account_indexes[position.account_id],
                    "code": position.code,
                    "cost_price": position.cost_price,
                    "cost_price_valid": position.cost_price_valid,
                    "currency": position.currency,
                    "market_val": position.market_val,
                    "nominal_price": position.nominal_price,
                    "pl_val": position.pl_val,
                    "pl_val_valid": position.pl_val_valid,
                    "position_side": position.position_side,
                    "qty": position.qty,
                    "stock_name": position.stock_name,
                }
                for position in self.positions
            ],
            "sync_state": self.sync_state,
        }


class MoomooConnectionService:
    """Owns one desktop-local, single-use OAuth connection attempt."""

    def __init__(
        self,
        *,
        oauth_transport: MoomooOAuthTransport,
        keychain_factory: Callable[[str], MoomooTokenKeychain],
        portfolio_client_factory: Callable[[str], MoomooPortfolioClient] | None = None,
        quote_stream_factory: Callable[
            [Callable[[], MoomooQuoteAccess]], DesktopMoomooQuoteStream
        ]
        | None = None,
        mcp_client_factory: Callable[[str], MoomooMcpDiscoveryClient]
        | None = None,
        mcp_keychain_factory: Callable[[str, str], MoomooMcpTokenKeychain]
        | None = None,
        mcp_oauth_client_id: str | None = None,
        mcp_oauth_transport: MoomooMcpOAuthTransport | None = None,
        mcp_client_identity_store: MoomooMcpClientIdentityStore | None = None,
        diagnostics_log: MoomooDiagnosticsLog | None = None,
        browser_opener: Callable[[str], bool] = webbrowser.open,
        callback_timeout_seconds: float = 180,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if callback_timeout_seconds <= 0:
            raise ValueError("Moomoo callback timeout must be positive")
        self._browser_opener = browser_opener
        self._callback_timeout_seconds = callback_timeout_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._keychain_factory = keychain_factory
        self._oauth_transport = oauth_transport
        self._portfolio_client_factory = portfolio_client_factory
        self._quote_stream_factory = quote_stream_factory
        self._mcp_client_factory = mcp_client_factory
        self._mcp_keychain_factory = mcp_keychain_factory
        self._mcp_oauth_client_id = mcp_oauth_client_id
        self._mcp_oauth_transport = mcp_oauth_transport
        self._mcp_client_identity_store = mcp_client_identity_store
        self._diagnostics_log = diagnostics_log
        self._lock = threading.Lock()
        self._mirror = MoomooHoldingsMirror(
            accounts=(),
            positions=(),
            sync_state="unavailable",
        )
        self._status = MoomooConnectionStatus(
            state="disconnected",
            account_count=0,
            position_count=0,
            sync_state="unavailable",
            error_code=None,
        )
        self._operator_id: str | None = None
        self._pending_operator_id: str | None = None
        self._client_id: str | None = None
        self._authorized_account_ids: tuple[str, ...] = ()
        self._capabilities: tuple[str, ...] = ()
        self._quote_stream: DesktopMoomooQuoteStream | None = None
        self._access_token: str | None = None
        self._mcp_access_token: str | None = None
        self._mcp_operator_id: str | None = None
        self._mcp_pending_operator_id: str | None = None
        self._mcp_status = MoomooMcpDiscoveryStatus(
            state="disconnected",
            tool_count=0,
        )
        self._last_market_quotes: dict[str, MoomooMarketQuoteStatus] = {}

    def status(self) -> MoomooConnectionStatus:
        with self._lock:
            return self._status

    def recent_diagnostics(self) -> list[Mapping[str, object]]:
        if self._diagnostics_log is None:
            return []
        return [entry.as_dict() for entry in self._diagnostics_log.recent()]

    def last_market_quote(self, *, security_id: str) -> MoomooMarketQuoteStatus:
        try:
            normalized_security_id = str(uuid.UUID(security_id))
        except ValueError as error:
            raise DesktopControlError(
                "moomoo_market_evidence_identity_invalid"
            ) from error
        with self._lock:
            entry = self._last_market_quotes.get(normalized_security_id)
        if entry is None:
            return MoomooMarketQuoteStatus(state="unavailable")
        return self._reclassify_cached_quote(entry)

    def _reclassify_cached_quote(
        self, entry: MoomooMarketQuoteStatus
    ) -> MoomooMarketQuoteStatus:
        if entry.evidence is None or entry.state not in {"ready", "stale"}:
            return replace(entry, cached=True)
        provider_reported_at_raw = entry.evidence.get("provider_reported_at")
        provider_reported_at = None
        if isinstance(provider_reported_at_raw, str):
            try:
                provider_reported_at = datetime.fromisoformat(provider_reported_at_raw)
            except ValueError:
                provider_reported_at = None
        freshness = classify_freshness(provider_reported_at, self._clock())
        state = "stale" if freshness == "stale" else entry.state
        evidence = dict(entry.evidence)
        evidence["freshness"] = freshness
        return replace(
            entry,
            state=state,
            error_code=(
                "moomoo_market_evidence_stale" if state == "stale" else entry.error_code
            ),
            evidence=evidence,
            cached=True,
        )

    def mcp_discovery_status(self) -> MoomooMcpDiscoveryStatus:
        with self._lock:
            return self._mcp_status

    def discover_mcp_tools(self, *, operator_id: str) -> MoomooMcpDiscoveryStatus:
        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
        except ValueError as error:
            raise DesktopControlError("moomoo_operator_id_invalid") from error
        with self._lock:
            connected_operator_id = self._mcp_operator_id
            mcp_access_token = self._mcp_access_token
            factory = self._mcp_client_factory
        if connected_operator_id != normalized_operator_id:
            raise DesktopControlError("moomoo_mcp_discovery_requires_connection")
        if not mcp_access_token:
            self._set_mcp_status(self._mcp_authorization_required_status())
            raise DesktopControlError("moomoo_mcp_authorization_required")
        if factory is None:
            self._set_mcp_status(
                MoomooMcpDiscoveryStatus(
                    state="unavailable",
                    tool_count=0,
                    error_code="moomoo_mcp_discovery_unavailable",
                )
            )
            raise DesktopControlError("moomoo_mcp_discovery_unavailable")
        try:
            advertised = factory(mcp_access_token).list_tools()
            summaries = _summarize_mcp_tools(advertised)
        except (MoomooMcpError, OSError, RuntimeError, TypeError, ValueError) as error:
            self._set_mcp_status(
                MoomooMcpDiscoveryStatus(
                    state="failed",
                    tool_count=0,
                    error_code="moomoo_mcp_discovery_failed",
                )
            )
            raise DesktopControlError("moomoo_mcp_discovery_failed") from error
        status = MoomooMcpDiscoveryStatus(
            state="ready",
            tool_count=len(summaries),
            tools=summaries,
        )
        self._set_mcp_status(status)
        return status

    def fetch_market_quote(
        self,
        *,
        operator_id: str,
        security_id: str,
        ticker: str,
        tool_name: str = MARKET_QUOTE_TOOL_NAME,
    ) -> MoomooMarketQuoteStatus:
        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
            normalized_security_id = str(uuid.UUID(security_id))
        except ValueError as error:
            raise DesktopControlError("moomoo_market_evidence_identity_invalid") from error
        if tool_name != MARKET_QUOTE_TOOL_NAME:
            raise DesktopControlError("moomoo_market_evidence_tool_not_allowlisted")
        if not isinstance(ticker, str) or not TICKER_PATTERN.match(ticker):
            raise DesktopControlError("moomoo_market_evidence_ticker_invalid")
        with self._lock:
            connected_operator_id = self._mcp_operator_id
            mcp_access_token = self._mcp_access_token
            factory = self._mcp_client_factory
            discovered_tool_names = {tool["name"] for tool in self._mcp_status.tools}
            discovery_ready = self._mcp_status.state == "ready"
        if connected_operator_id != normalized_operator_id:
            raise DesktopControlError("moomoo_mcp_discovery_requires_connection")
        if not mcp_access_token or factory is None:
            raise DesktopControlError("moomoo_mcp_authorization_required")
        if not discovery_ready or tool_name not in discovered_tool_names:
            raise DesktopControlError("moomoo_mcp_discovery_required")
        try:
            raw_result = factory(mcp_access_token).call_tool(
                tool_name, {"code_list": [ticker]}
            )
        except MoomooMcpError as error:
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="market_quote_failed",
                reason_code=error.code,
            )
            status = MoomooMarketQuoteStatus(
                state="failed",
                error_code="moomoo_market_evidence_request_failed",
            )
            self._store_last_market_quote(normalized_security_id, status)
            return status
        try:
            evidence = build_market_quote_evidence(
                raw_result,
                ticker=ticker,
                security_id=normalized_security_id,
                retrieved_at=self._clock(),
            )
        except MarketEvidenceError as error:
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="market_quote_malformed",
                reason_code=error.code,
                shape=summarize_mcp_result_shape(raw_result),
            )
            status = MoomooMarketQuoteStatus(
                state="malformed",
                error_code="moomoo_market_evidence_malformed",
            )
            self._store_last_market_quote(normalized_security_id, status)
            return status
        if evidence.is_error:
            status = MoomooMarketQuoteStatus(
                state="failed",
                error_code=evidence.failure_reason,
                evidence=evidence.as_dict(),
            )
            self._store_last_market_quote(normalized_security_id, status)
            return status
        status = MoomooMarketQuoteStatus(
            state="stale" if evidence.freshness == "stale" else "ready",
            error_code="moomoo_market_evidence_stale" if evidence.freshness == "stale" else None,
            evidence=evidence.as_dict(),
        )
        self._store_last_market_quote(normalized_security_id, status)
        return status

    def fetch_market_history(
        self,
        *,
        operator_id: str,
        security_id: str,
        ticker: str,
        start: str,
        end: str,
        max_bars: int,
    ) -> MoomooMarketQuoteStatus:
        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
            normalized_security_id = str(uuid.UUID(security_id))
            arguments = build_daily_history_arguments(
                ticker=ticker,
                start=date.fromisoformat(start),
                end=date.fromisoformat(end),
                max_bars=max_bars,
            )
        except (ValueError, HistoryEvidenceError) as error:
            raise DesktopControlError("moomoo_market_history_request_invalid") from error
        with self._lock:
            connected_operator_id = self._mcp_operator_id
            access_token = self._mcp_access_token
            factory = self._mcp_client_factory
            discovered = {tool["name"] for tool in self._mcp_status.tools}
            ready = self._mcp_status.state == "ready"
        if connected_operator_id != normalized_operator_id:
            raise DesktopControlError("moomoo_mcp_discovery_requires_connection")
        if not access_token or factory is None:
            raise DesktopControlError("moomoo_mcp_authorization_required")
        if not ready or HISTORY_TOOL_NAME not in discovered:
            raise DesktopControlError("moomoo_mcp_discovery_required")
        try:
            raw_result = factory(access_token).call_tool(HISTORY_TOOL_NAME, arguments)
            evidence = build_market_history_evidence(
                raw_result,
                ticker=ticker,
                security_id=normalized_security_id,
                retrieved_at=self._clock(),
            )
        except MoomooMcpError as error:
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="market_history_failed",
                reason_code=error.code,
            )
            return MoomooMarketQuoteStatus(
                state="failed", error_code="moomoo_market_history_request_failed"
            )
        except HistoryEvidenceError as error:
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="market_history_malformed",
                reason_code=error.code,
            )
            return MoomooMarketQuoteStatus(
                state="malformed", error_code="moomoo_market_history_malformed"
            )
        return MoomooMarketQuoteStatus(state="ready", evidence=evidence.as_dict())

    def _store_last_market_quote(
        self, security_id: str, status: MoomooMarketQuoteStatus
    ) -> None:
        with self._lock:
            self._last_market_quotes[security_id] = status

    def holdings(self) -> MoomooHoldingsMirror:
        with self._lock:
            return self._mirror

    def refresh_mcp_holdings(self, *, operator_id: str) -> MoomooHoldingsMirror:
        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
        except ValueError as error:
            raise DesktopControlError("moomoo_operator_id_invalid") from error
        with self._lock:
            connected_operator_id = self._mcp_operator_id
            access_token = self._mcp_access_token
            factory = self._mcp_client_factory
            discovered = {tool["name"] for tool in self._mcp_status.tools}
            ready = self._mcp_status.state == "ready"
        if connected_operator_id != normalized_operator_id:
            raise DesktopControlError("moomoo_mcp_discovery_requires_connection")
        if not access_token or factory is None:
            raise DesktopControlError("moomoo_mcp_authorization_required")
        if not ready or not {ACCOUNT_TOOL_NAME, POSITIONS_TOOL_NAME} <= discovered:
            raise DesktopControlError("moomoo_mcp_portfolio_tools_unavailable")
        client = factory(access_token)
        try:
            accounts = normalize_mcp_accounts(client.call_tool(ACCOUNT_TOOL_NAME, {}))
            positions = tuple(
                position
                for account in accounts
                for position in normalize_mcp_positions(
                    client.call_tool(POSITIONS_TOOL_NAME, {"acc_id": account.account_id}),
                    account_id=account.account_id,
                )
            )
        except MoomooMcpError as error:
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="portfolio_read_failed",
                reason_code=error.code,
            )
            raise DesktopControlError("moomoo_mcp_portfolio_request_failed") from error
        except MoomooMcpPortfolioError as error:
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="portfolio_read_malformed",
                reason_code=error.code,
            )
            raise DesktopControlError("moomoo_mcp_portfolio_malformed") from error
        mirror = MoomooHoldingsMirror(
            accounts=accounts,
            positions=positions,
            sync_state="ready",
        )
        with self._lock:
            self._mirror = mirror
        return mirror

    def quotes(self) -> MoomooQuoteStreamSnapshot:
        with self._lock:
            quote_stream = self._quote_stream
        if quote_stream is None:
            return MoomooQuoteStreamSnapshot(
                state="unavailable",
                symbols=(),
                quotes=(),
                error_code=None,
            )
        return quote_stream.snapshot()

    def replace_quote_symbols(
        self,
        *,
        operator_id: str,
        symbols: tuple[str, ...],
    ) -> MoomooQuoteStreamSnapshot:
        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
        except ValueError as error:
            raise DesktopControlError("moomoo_operator_id_invalid") from error
        with self._lock:
            connected_operator_id = self._operator_id
            capabilities = self._capabilities
            quote_stream = self._quote_stream
        if connected_operator_id != normalized_operator_id:
            raise DesktopControlError("moomoo_connected_operator_mismatch")
        if "market_data" not in capabilities or quote_stream is None:
            raise DesktopControlError("moomoo_market_data_capability_unavailable")
        try:
            validator = MoomooQuoteSubscriptionBook()
            validator.replace(symbols)
            quote_stream.replace_symbols(validator.symbols)
        except (MoomooQuoteLimitError, MoomooQuoteProtocolError, ValueError) as error:
            raise DesktopControlError("moomoo_quote_subscription_invalid") from error
        return quote_stream.snapshot()

    def disconnect(self, *, operator_id: str) -> MoomooConnectionStatus:
        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
        except ValueError as error:
            raise DesktopControlError("moomoo_operator_id_invalid") from error
        with self._lock:
            owning_operator_id = self._operator_id or self._pending_operator_id
            if (
                owning_operator_id is not None
                and owning_operator_id != normalized_operator_id
            ):
                raise DesktopControlError("moomoo_connected_operator_mismatch")
            quote_stream = self._quote_stream
            self._pending_operator_id = None
            self._status = MoomooConnectionStatus(
                state="disconnecting",
                account_count=0,
                position_count=0,
                sync_state="pending",
                error_code=None,
            )
        try:
            self._keychain_factory(normalized_operator_id).delete_refresh_token()
            if quote_stream is not None:
                quote_stream.stop()
        except (MoomooKeychainError, OSError, RuntimeError, ValueError) as error:
            self._set_failed("moomoo_disconnect_failed")
            raise DesktopControlError("moomoo_disconnect_failed") from error
        status = MoomooConnectionStatus(
            state="disconnected",
            account_count=0,
            position_count=0,
            sync_state="unavailable",
            error_code=None,
        )
        with self._lock:
            self._mirror = MoomooHoldingsMirror(
                accounts=(),
                positions=(),
                sync_state="unavailable",
            )
            self._operator_id = None
            self._pending_operator_id = None
            self._client_id = None
            self._access_token = None
            self._authorized_account_ids = ()
            self._capabilities = ()
            self._quote_stream = None
            self._status = status
        return status

    def refresh_holdings(
        self,
        *,
        operator_id: str,
    ) -> MoomooConnectionStatus:
        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
        except ValueError as error:
            raise DesktopControlError("moomoo_operator_id_invalid") from error
        with self._lock:
            connected_operator_id = self._operator_id
            client_id = self._client_id
            expected_account_ids = self._authorized_account_ids
            capabilities = self._capabilities
            previous_mirror = self._mirror
        if connected_operator_id != normalized_operator_id or client_id is None:
            raise DesktopControlError("moomoo_connected_operator_mismatch")
        if "portfolio_holdings" not in capabilities:
            raise DesktopControlError("moomoo_holdings_capability_unavailable")
        if self._portfolio_client_factory is None:
            raise DesktopControlError("moomoo_holdings_sync_unavailable")
        try:
            keychain = self._keychain_factory(normalized_operator_id)
            refresh_token = keychain.read_refresh_token()
            refreshed = refresh_access_token(
                client_id=client_id,
                refresh_token=refresh_token,
                required_read_scopes=READ_ONLY_SCOPES,
                transport=self._oauth_transport,
            )
            if refreshed.refresh_token is not None:
                keychain.store_refresh_token(refreshed.refresh_token)
            refreshed_capabilities = _granted_capabilities(
                read_scopes=refreshed.read_scopes,
                account_ids=refreshed.account_ids,
            )
            if "portfolio_holdings" not in refreshed_capabilities:
                status = MoomooConnectionStatus(
                    state="connected",
                    account_count=len(refreshed.account_ids),
                    position_count=0,
                    sync_state="unavailable",
                    error_code=None,
                    capabilities=refreshed_capabilities,
                )
                with self._lock:
                    if (
                        self._operator_id != normalized_operator_id
                        or self._client_id != client_id
                        or self._authorized_account_ids != expected_account_ids
                    ):
                        raise DesktopControlError("moomoo_connection_changed")
                    self._mirror = MoomooHoldingsMirror(
                        accounts=(),
                        positions=(),
                        sync_state="unavailable",
                    )
                    self._authorized_account_ids = refreshed.account_ids
                    self._capabilities = refreshed_capabilities
                    self._access_token = refreshed.access_token
                    self._status = status
                return status
            if tuple(sorted(refreshed.account_ids)) != tuple(
                sorted(expected_account_ids)
            ):
                raise RuntimeError("Moomoo authorized account mismatch")
            accounts, positions = self._load_holdings(
                self._portfolio_client_factory(refreshed.access_token),
                expected_account_ids=expected_account_ids,
            )
        except (
            MoomooKeychainError,
            MoomooOAuthError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            self._set_status(
                MoomooConnectionStatus(
                    state="connected",
                    account_count=len(previous_mirror.accounts),
                    position_count=len(previous_mirror.positions),
                    sync_state="failed",
                    error_code="moomoo_holdings_refresh_failed",
                    capabilities=capabilities,
                )
            )
            raise DesktopControlError("moomoo_holdings_refresh_failed") from error
        status = MoomooConnectionStatus(
            state="connected",
            account_count=len(accounts),
            position_count=len(positions),
            sync_state="ready",
            error_code=None,
            capabilities=refreshed_capabilities,
        )
        with self._lock:
            if (
                self._operator_id != normalized_operator_id
                or self._client_id != client_id
                or self._authorized_account_ids != expected_account_ids
            ):
                raise DesktopControlError("moomoo_connection_changed")
            self._mirror = MoomooHoldingsMirror(
                accounts=accounts,
                positions=positions,
                sync_state="ready",
            )
            self._capabilities = refreshed_capabilities
            self._access_token = refreshed.access_token
            self._status = status
        return status

    def resume_connection(
        self,
        *,
        client_id: str,
        operator_id: str,
    ) -> MoomooConnectionStatus:
        """Restore one saved read-only session without opening browser OAuth."""
        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
            normalized_client_id = str(uuid.UUID(client_id))
        except ValueError as error:
            raise DesktopControlError("moomoo_resume_request_invalid") from error
        with self._lock:
            if self._status.state == "connected":
                if self._operator_id != normalized_operator_id:
                    raise DesktopControlError("moomoo_connected_operator_mismatch")
                return self._status
            if self._status.state in {"pending", "disconnecting"}:
                raise DesktopControlError("moomoo_connection_already_pending")
            previous_quote_stream = self._quote_stream
            self._mirror = MoomooHoldingsMirror(
                accounts=(),
                positions=(),
                sync_state="unavailable",
            )
            self._operator_id = None
            self._pending_operator_id = normalized_operator_id
            self._client_id = None
            self._access_token = None
            self._authorized_account_ids = ()
            self._capabilities = ()
            self._status = MoomooConnectionStatus(
                state="pending",
                account_count=0,
                position_count=0,
                sync_state="pending",
                error_code=None,
            )
        if previous_quote_stream is not None:
            try:
                previous_quote_stream.stop()
            except (OSError, RuntimeError, ValueError) as error:
                self._set_resume_failed(
                    operator_id=normalized_operator_id,
                    error_code="moomoo_quote_stream_stop_failed",
                )
                raise DesktopControlError("moomoo_quote_stream_stop_failed") from error
            with self._lock:
                if self._quote_stream is previous_quote_stream:
                    self._quote_stream = None

        quote_stream: DesktopMoomooQuoteStream | None = None
        try:
            keychain = self._keychain_factory(normalized_operator_id)
            refresh_token = keychain.read_refresh_token()
            refreshed = refresh_access_token(
                client_id=normalized_client_id,
                refresh_token=refresh_token,
                required_read_scopes=READ_ONLY_SCOPES,
                transport=self._oauth_transport,
            )
            if refreshed.refresh_token is not None:
                keychain.store_refresh_token(refreshed.refresh_token)
            capabilities = _granted_capabilities(
                read_scopes=refreshed.read_scopes,
                account_ids=refreshed.account_ids,
            )
            if "market_data" in capabilities and self._quote_stream_factory is not None:
                quote_stream = self._quote_stream_factory(
                    lambda: self._refresh_quote_access(
                        operator_id=normalized_operator_id,
                        client_id=normalized_client_id,
                    )
                )
                quote_stream.start(
                    MoomooQuoteAccess(
                        access_token=refreshed.access_token,
                        expires_in=refreshed.expires_in,
                    )
                )
            if (
                self._portfolio_client_factory is not None
                and "portfolio_holdings" in capabilities
            ):
                accounts, positions = self._load_holdings(
                    self._portfolio_client_factory(refreshed.access_token),
                    expected_account_ids=refreshed.account_ids,
                )
                mirror = MoomooHoldingsMirror(
                    accounts=accounts,
                    positions=positions,
                    sync_state="ready",
                )
                sync_state = "ready"
            else:
                accounts = ()
                positions = ()
                mirror = MoomooHoldingsMirror(
                    accounts=(),
                    positions=(),
                    sync_state="unavailable",
                )
                sync_state = "unavailable"
        except (
            MoomooKeychainError,
            MoomooOAuthError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            if quote_stream is not None:
                quote_stream.stop()
            self._set_resume_failed(
                operator_id=normalized_operator_id,
                error_code="moomoo_saved_authorization_unavailable",
            )
            raise DesktopControlError(
                "moomoo_saved_authorization_unavailable"
            ) from error

        status = MoomooConnectionStatus(
            state="connected",
            account_count=len(refreshed.account_ids),
            position_count=len(positions),
            sync_state=sync_state,
            error_code=None,
            capabilities=capabilities,
        )
        with self._lock:
            if (
                self._status.state != "pending"
                or self._pending_operator_id != normalized_operator_id
            ):
                connection_changed = True
            else:
                connection_changed = False
                self._mirror = mirror
                self._operator_id = normalized_operator_id
                self._pending_operator_id = None
                self._client_id = normalized_client_id
                self._access_token = refreshed.access_token
                self._authorized_account_ids = refreshed.account_ids
                self._capabilities = capabilities
                self._quote_stream = quote_stream
                self._status = status
        if connection_changed:
            if quote_stream is not None:
                quote_stream.stop()
            raise DesktopControlError("moomoo_connection_changed")
        return status

    def start_mcp_authorization(
        self,
        *,
        operator_id: str,
        redirect_uri: str,
    ) -> MoomooMcpDiscoveryStatus:
        """Start the core Moomoo (MCP) connection.

        Fully independent of any OpenAPI/WebSocket streaming connection: no
        prior OpenAPI authorization is required or consulted here, and this
        never reuses the OpenAPI OAuth helper/transport/token.
        """

        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
        except ValueError as error:
            raise DesktopControlError("moomoo_operator_id_invalid") from error
        with self._lock:
            if (
                self._mcp_keychain_factory is None
                or self._mcp_client_factory is None
                or self._mcp_oauth_transport is None
            ):
                raise DesktopControlError("moomoo_mcp_authorization_unavailable")
            if self._mcp_status.state == "authorizing":
                raise DesktopControlError("moomoo_mcp_authorization_already_pending")
            self._mcp_pending_operator_id = normalized_operator_id
            self._mcp_status = MoomooMcpDiscoveryStatus(
                state="authorizing",
                tool_count=0,
            )
        attempt = create_mcp_pkce_attempt()
        try:
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="metadata_discovery_started",
                reason_code="started",
            )
            issuers = fetch_protected_resource_metadata(self._mcp_oauth_transport)
            authorization_server = fetch_authorization_server_metadata(
                self._mcp_oauth_transport, issuer=issuers[0]
            )
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="metadata_discovery_ready",
                reason_code="ready",
            )
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="client_identity_resolution_started",
                reason_code="started",
            )
            client_id = self._resolve_mcp_client_id(
                redirect_uri=redirect_uri, authorization_server=authorization_server
            )
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="client_identity_resolution_ready",
                reason_code="ready",
            )
            authorization_url = build_mcp_authorization_url(
                authorization_endpoint=authorization_server.authorization_endpoint,
                client_id=client_id,
                redirect_uri=redirect_uri,
                attempt=attempt,
            )
            parsed_redirect = urlsplit(redirect_uri)
            if parsed_redirect.port is None:
                raise ValueError
            callback_server = HTTPServer(
                ("127.0.0.1", parsed_redirect.port),
                _OAuthCallbackHandler,
            )
        except MoomooMcpOAuthError as error:
            self._set_mcp_failed(error.code)
            raise DesktopControlError(error.code) from error
        except (OSError, ValueError) as error:
            self._set_mcp_failed("moomoo_mcp_authorization_request_invalid")
            raise DesktopControlError(
                "moomoo_mcp_authorization_request_invalid"
            ) from error
        try:
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="browser_authorization_started",
                reason_code="started",
            )
            browser_opened = self._browser_opener(authorization_url)
        except OSError:
            browser_opened = False
        if not browser_opened:
            callback_server.server_close()
            self._set_mcp_failed("moomoo_system_browser_unavailable")
            raise DesktopControlError("moomoo_system_browser_unavailable")
        self._record_diagnostic(
            subsystem="core_mcp",
            stage="browser_authorization_ready",
            reason_code="ready",
        )
        thread = threading.Thread(
            target=self._complete_mcp_connection,
            args=(
                callback_server,
                attempt,
                client_id,
                authorization_server,
                normalized_operator_id,
                redirect_uri,
            ),
            daemon=True,
            name="iros-moomoo-mcp-oauth-callback",
        )
        thread.start()
        return self.mcp_discovery_status()

    def _current_mcp_client_id(self) -> str | None:
        """Read-only lookup of an already-established client ID, if any.

        Never triggers a new dynamic registration; used by paths (refresh,
        disconnect) that must reuse a previously bound identity rather than
        create one.
        """

        if self._mcp_oauth_client_id is not None:
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="client_identity_override_reused",
                reason_code="ready",
            )
            return self._mcp_oauth_client_id
        if self._mcp_client_identity_store is not None:
            return self._mcp_client_identity_store.load_any(resource=MOOMOO_MCP_RESOURCE)
        return None

    def _resolve_mcp_client_id(
        self,
        *,
        redirect_uri: str,
        authorization_server: MoomooMcpAuthorizationServer,
    ) -> str:
        """Resolve a usable MCP OAuth client ID without a required env var.

        Precedence: an explicit `mcp_oauth_client_id` override (advanced/
        manual operator setup) first; otherwise a previously persisted
        dynamic registration bound to this exact resource+redirect URI;
        otherwise a fresh RFC 7591 dynamic registration, persisted for
        future launches. Fails closed with `client_registration_unavailable`
        (raised inside `register_mcp_client`) if none of these produce a
        client ID, rather than fabricating one.
        """

        if self._mcp_oauth_client_id is not None:
            return self._mcp_oauth_client_id
        if self._mcp_client_identity_store is not None:
            existing = self._mcp_client_identity_store.load(
                resource=MOOMOO_MCP_RESOURCE, redirect_uri=redirect_uri
            )
            if existing is not None:
                self._record_diagnostic(
                    subsystem="core_mcp",
                    stage="client_identity_persisted_reused",
                    reason_code="ready",
                )
                return existing
        self._record_diagnostic(
            subsystem="core_mcp",
            stage="client_registration_started",
            reason_code="started",
        )
        registration = register_mcp_client(
            self._mcp_oauth_transport,
            authorization_server=authorization_server,
            redirect_uri=redirect_uri,
        )
        if self._mcp_client_identity_store is not None:
            self._mcp_client_identity_store.save(
                MoomooMcpClientIdentity(
                    client_id=registration.client_id,
                    resource=MOOMOO_MCP_RESOURCE,
                    redirect_uri=redirect_uri,
                )
            )
        self._record_diagnostic(
            subsystem="core_mcp",
            stage="client_registration_ready",
            reason_code="ready",
        )
        return registration.client_id

    def _complete_mcp_connection(
        self,
        callback_server: HTTPServer,
        attempt: PkceAuthorizationAttempt,
        client_id: str,
        authorization_server: MoomooMcpAuthorizationServer,
        operator_id: str,
        redirect_uri: str,
    ) -> None:
        callback_server.timeout = self._callback_timeout_seconds
        callback_server.handle_request()
        callback = getattr(callback_server, "oauth_callback", None)
        callback_server.server_close()
        if not isinstance(callback, Mapping):
            self._consume_failed_attempt(attempt)
            self._set_mcp_failed("callback_timeout")
            return
        code = callback.get("code")
        state = callback.get("state")
        if not isinstance(code, str) or not isinstance(state, str):
            self._consume_failed_attempt(attempt)
            self._set_mcp_failed("callback_state_invalid")
            return
        try:
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="token_exchange_started",
                reason_code="started",
            )
            tokens = exchange_mcp_authorization_code(
                token_endpoint=authorization_server.token_endpoint,
                client_id=client_id,
                redirect_uri=redirect_uri,
                authorization_code=code,
                callback_state=state,
                attempt=attempt,
                transport=self._mcp_oauth_transport,
            )
            self._mcp_keychain_factory(operator_id, client_id).store_refresh_token(
                tokens.refresh_token
            )
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="token_exchange_ready",
                reason_code="ready",
            )
        except MoomooMcpOAuthError as error:
            self._set_mcp_failed(error.code)
            return
        except (MoomooKeychainError, OSError, RuntimeError, ValueError):
            self._set_mcp_failed("keychain_write_failed")
            return
        with self._lock:
            if (
                self._mcp_status.state != "authorizing"
                or self._mcp_pending_operator_id != operator_id
            ):
                self._consume_failed_attempt(attempt)
                return
            self._mcp_operator_id = operator_id
            self._mcp_pending_operator_id = None
            self._mcp_access_token = tokens.access_token
        self._set_mcp_status(
            MoomooMcpDiscoveryStatus(state="discovering", tool_count=0)
        )
        self._record_diagnostic(
            subsystem="core_mcp",
            stage="tool_discovery_started",
            reason_code="started",
        )
        self._run_mcp_discovery(operator_id=operator_id)

    def resume_mcp_connection(self, *, operator_id: str) -> MoomooMcpDiscoveryStatus:
        """Restore the core Moomoo (MCP) connection with no browser popup.

        Independent of the optional OpenAPI/WebSocket streaming connection:
        never reads, requires, or is blocked by its state, credential, or
        transport. One bounded attempt per call; a missing or rejected
        credential returns `reconnect_required` rather than looping.
        """

        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
        except ValueError as error:
            raise DesktopControlError("moomoo_operator_id_invalid") from error
        with self._lock:
            if (
                self._mcp_status.state == "ready"
                and self._mcp_operator_id == normalized_operator_id
            ):
                return self._mcp_status
            if (
                self._mcp_status.state in {"refreshing", "discovering"}
                and self._mcp_pending_operator_id == normalized_operator_id
            ):
                return self._mcp_status
            self._mcp_pending_operator_id = normalized_operator_id
            self._mcp_status = MoomooMcpDiscoveryStatus(state="refreshing", tool_count=0)
        self._record_diagnostic(
            subsystem="core_mcp", stage="refresh_started", reason_code="started"
        )
        client_id = self._current_mcp_client_id()
        if (
            self._mcp_keychain_factory is None
            or self._mcp_client_factory is None
            or self._mcp_oauth_transport is None
            or client_id is None
        ):
            status = MoomooMcpDiscoveryStatus(
                state="reconnect_required",
                tool_count=0,
                error_code="credential_missing",
            )
            self._set_mcp_status(status)
            return status
        self._record_diagnostic(
            subsystem="core_mcp",
            stage="refresh_client_identity_ready",
            reason_code="ready",
        )
        try:
            keychain = self._mcp_keychain_factory(normalized_operator_id, client_id)
            refresh_token = keychain.read_refresh_token()
        except MoomooMcpCredentialError as error:
            status = MoomooMcpDiscoveryStatus(
                state="reconnect_required", tool_count=0, error_code=error.code
            )
            self._set_mcp_status(status)
            return status
        self._record_diagnostic(
            subsystem="core_mcp", stage="refresh_credential_ready", reason_code="ready"
        )
        try:
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="refresh_metadata_started",
                reason_code="started",
            )
            issuers = fetch_protected_resource_metadata(self._mcp_oauth_transport)
            authorization_server = fetch_authorization_server_metadata(
                self._mcp_oauth_transport, issuer=issuers[0]
            )
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="refresh_metadata_ready",
                reason_code="ready",
            )
            self._record_diagnostic(
                subsystem="core_mcp",
                stage="refresh_token_started",
                reason_code="started",
            )
            refreshed = refresh_mcp_access_token(
                token_endpoint=authorization_server.token_endpoint,
                client_id=client_id,
                refresh_token=refresh_token,
                transport=self._mcp_oauth_transport,
            )
            self._record_diagnostic(
                subsystem="core_mcp", stage="refresh_token_ready", reason_code="ready"
            )
        except MoomooMcpOAuthError as error:
            status = MoomooMcpDiscoveryStatus(
                state="reconnect_required", tool_count=0, error_code=error.code
            )
            self._set_mcp_status(status)
            return status
        if refreshed.refresh_token is not None:
            try:
                keychain.store_refresh_token(refreshed.refresh_token)
            except (MoomooKeychainError, OSError, RuntimeError, ValueError):
                status = MoomooMcpDiscoveryStatus(
                    state="reconnect_required",
                    tool_count=0,
                    error_code="keychain_write_failed",
                )
                self._set_mcp_status(status)
                return status
        with self._lock:
            if self._mcp_pending_operator_id != normalized_operator_id:
                return self._mcp_status
            self._mcp_operator_id = normalized_operator_id
            self._mcp_pending_operator_id = None
            self._mcp_access_token = refreshed.access_token
        self._set_mcp_status(
            MoomooMcpDiscoveryStatus(state="discovering", tool_count=0)
        )
        self._record_diagnostic(
            subsystem="core_mcp",
            stage="tool_discovery_started",
            reason_code="started",
        )
        return self._run_mcp_discovery(operator_id=normalized_operator_id)

    def _run_mcp_discovery(self, *, operator_id: str) -> MoomooMcpDiscoveryStatus:
        try:
            return self.discover_mcp_tools(operator_id=operator_id)
        except DesktopControlError:
            return self.mcp_discovery_status()

    def disconnect_mcp(self, *, operator_id: str) -> MoomooMcpDiscoveryStatus:
        """Disconnect only the core Moomoo (MCP) connection.

        Records an intentional local opt-out (the MCP credential is
        deleted, so no later `resume_mcp_connection` silently reconnects)
        without touching the optional OpenAPI/WebSocket streaming
        credential or state. Does not revoke authorization at the
        provider; the operator's broker-side grant is unaffected.
        """

        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
        except ValueError as error:
            raise DesktopControlError("moomoo_operator_id_invalid") from error
        with self._lock:
            owning_operator_id = self._mcp_operator_id or self._mcp_pending_operator_id
            if (
                owning_operator_id is not None
                and owning_operator_id != normalized_operator_id
            ):
                raise DesktopControlError("moomoo_connected_operator_mismatch")
        client_id = self._current_mcp_client_id()
        if self._mcp_keychain_factory is not None and client_id is not None:
            try:
                self._mcp_keychain_factory(
                    normalized_operator_id, client_id
                ).delete_refresh_token()
            except (MoomooKeychainError, OSError, RuntimeError, ValueError) as error:
                raise DesktopControlError("keychain_write_failed") from error
        with self._lock:
            self._mcp_access_token = None
            self._mcp_operator_id = None
            self._mcp_pending_operator_id = None
            self._mcp_status = MoomooMcpDiscoveryStatus(
                state="disconnected",
                tool_count=0,
            )
            self._last_market_quotes = {}
        self._record_diagnostic(
            subsystem="core_mcp", stage="disconnected", reason_code="operator_requested"
        )
        return self.mcp_discovery_status()

    def disconnect_all(self, *, operator_id: str) -> None:
        """Clear all local Moomoo authorization and connection metadata.

        Security registry, research notebook, and portfolio snapshot stores are
        separate repositories and are deliberately outside this operation.
        """

        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
        except ValueError as error:
            raise DesktopControlError("moomoo_operator_id_invalid") from error
        client_id = self._current_mcp_client_id()
        self.disconnect_mcp(operator_id=operator_id)
        self.disconnect(operator_id=operator_id)
        try:
            if self._mcp_keychain_factory is not None and client_id is not None:
                self._mcp_keychain_factory(
                    normalized_operator_id, client_id
                ).clear_all_local_tokens()
            if self._mcp_client_identity_store is not None:
                self._mcp_client_identity_store.clear()
        except (MoomooKeychainError, OSError, RuntimeError, ValueError) as error:
            raise DesktopControlError("moomoo_clear_all_failed") from error
        if self._diagnostics_log is not None:
            self._diagnostics_log.clear()

    def compose_holdings(
        self,
        *,
        operator_id: str,
        candidates: tuple[CanonicalSecurityCandidate, ...],
        checked_at: datetime,
    ) -> MoomooSnapshotComposition:
        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
        except ValueError as error:
            raise DesktopControlError("moomoo_operator_id_invalid") from error
        if checked_at.tzinfo is None:
            raise DesktopControlError("moomoo_compose_request_invalid")
        with self._lock:
            mirror = self._mirror
            connected_operator_id = self._operator_id
        if connected_operator_id != normalized_operator_id:
            raise DesktopControlError("moomoo_connected_operator_mismatch")
        if mirror.sync_state != "ready":
            raise DesktopControlError("moomoo_holdings_not_ready")
        try:
            snapshots = tuple(
                MoomooComposedAccountSnapshot(
                    account_label=f"Moomoo account {account_index}",
                    account_type=account.acc_type,
                    security_firm=account.security_firm,
                    snapshot=build_portfolio_snapshot(
                        operator_id=normalized_operator_id,
                        provider="moomoo_rest",
                        provider_transport="web_rest_oauth",
                        provider_account_id=account.account_id,
                        positions=tuple(
                            position
                            for position in mirror.positions
                            if position.account_id == account.account_id
                        ),
                        candidates=candidates,
                        captured_at=checked_at,
                    ),
                )
                for account_index, account in enumerate(
                    sorted(mirror.accounts, key=lambda item: item.account_id),
                    start=1,
                )
            )
        except (RuntimeError, ValueError) as error:
            raise DesktopControlError("moomoo_portfolio_compose_failed") from error
        return MoomooSnapshotComposition(snapshots=snapshots)

    def start_connection(
        self,
        *,
        client_id: str,
        operator_id: str,
        redirect_uri: str,
    ) -> MoomooConnectionStatus:
        try:
            normalized_operator_id = str(uuid.UUID(operator_id))
        except ValueError as error:
            raise DesktopControlError("moomoo_operator_id_invalid") from error

        attempt = create_pkce_attempt()
        try:
            authorization_url = build_authorization_url(
                client_id=client_id,
                redirect_uri=redirect_uri,
                attempt=attempt,
            )
        except MoomooOAuthError as error:
            raise DesktopControlError("moomoo_connection_request_invalid") from error

        with self._lock:
            if self._status.state in {"pending", "disconnecting"}:
                raise DesktopControlError("moomoo_connection_already_pending")
            previous_quote_stream = self._quote_stream
            self._mirror = MoomooHoldingsMirror(
                accounts=(),
                positions=(),
                sync_state="unavailable",
            )
            self._operator_id = None
            self._pending_operator_id = normalized_operator_id
            self._client_id = None
            self._access_token = None
            self._authorized_account_ids = ()
            self._capabilities = ()
            self._quote_stream = None
            self._status = MoomooConnectionStatus(
                state="pending",
                account_count=0,
                position_count=0,
                sync_state="pending",
                error_code=None,
            )
        if previous_quote_stream is not None:
            previous_quote_stream.stop()

        callback_server = self._create_callback_server(
            redirect_uri=redirect_uri,
        )
        try:
            browser_opened = self._browser_opener(authorization_url)
        except OSError:
            browser_opened = False
        if not browser_opened:
            callback_server.server_close()
            self._set_failed("moomoo_system_browser_unavailable")
            raise DesktopControlError("moomoo_system_browser_unavailable")
        thread = threading.Thread(
            target=self._complete_connection,
            args=(
                callback_server,
                attempt,
                client_id,
                normalized_operator_id,
                redirect_uri,
            ),
            daemon=True,
            name="iros-moomoo-oauth-callback",
        )
        thread.start()
        return self.status()

    def _create_callback_server(
        self,
        *,
        redirect_uri: str,
    ) -> HTTPServer:
        parsed = urlsplit(redirect_uri)
        if parsed.port is None:
            raise DesktopControlError("moomoo_connection_request_invalid")
        try:
            return HTTPServer(
                ("127.0.0.1", parsed.port),
                _OAuthCallbackHandler,
            )
        except OSError as error:
            self._set_failed("moomoo_callback_bind_failed")
            raise DesktopControlError("moomoo_callback_bind_failed") from error

    def _complete_connection(
        self,
        callback_server: HTTPServer,
        attempt: PkceAuthorizationAttempt,
        client_id: str,
        operator_id: str,
        redirect_uri: str,
    ) -> None:
        callback_server.timeout = self._callback_timeout_seconds
        callback_server.handle_request()
        callback = getattr(callback_server, "oauth_callback", None)
        callback_server.server_close()
        if not isinstance(callback, Mapping):
            self._consume_failed_attempt(attempt)
            self._set_failed("moomoo_oauth_callback_timeout")
            return
        code = callback.get("code")
        state = callback.get("state")
        if not isinstance(code, str) or not isinstance(state, str):
            self._consume_failed_attempt(attempt)
            self._set_failed("moomoo_oauth_callback_invalid")
            return
        try:
            tokens = exchange_authorization_code(
                client_id=client_id,
                redirect_uri=redirect_uri,
                authorization_code=code,
                callback_state=state,
                attempt=attempt,
                required_read_scopes=READ_ONLY_SCOPES,
                transport=self._oauth_transport,
            )
            self._keychain_factory(operator_id).store_refresh_token(
                tokens.refresh_token
            )
        except MoomooOAuthError as error:
            self._set_failed(_oauth_failure_code(error))
            return
        except (MoomooKeychainError, OSError, RuntimeError, ValueError):
            self._set_failed("moomoo_keychain_store_failed")
            return
        with self._lock:
            if (
                self._status.state != "pending"
                or self._pending_operator_id != operator_id
            ):
                self._consume_failed_attempt(attempt)
                return
            self._operator_id = operator_id
            self._pending_operator_id = None
            self._client_id = client_id
            self._access_token = tokens.access_token
            self._authorized_account_ids = tokens.account_ids
            self._capabilities = _granted_capabilities(
                read_scopes=tokens.read_scopes,
                account_ids=tokens.account_ids,
            )
            capabilities = self._capabilities
        if "market_data" in capabilities and self._quote_stream_factory is not None:
            quote_stream = self._quote_stream_factory(
                lambda: self._refresh_quote_access(
                    operator_id=operator_id,
                    client_id=client_id,
                )
            )
            try:
                quote_stream.start(
                    MoomooQuoteAccess(
                        access_token=tokens.access_token,
                        expires_in=tokens.expires_in,
                    )
                )
            except (OSError, RuntimeError, ValueError):
                self._set_failed("moomoo_quote_stream_start_failed")
                return
            with self._lock:
                connection_changed = (
                    self._operator_id != operator_id or self._client_id != client_id
                )
                if not connection_changed:
                    self._quote_stream = quote_stream
            if connection_changed:
                quote_stream.stop()
                self._set_failed("moomoo_connection_changed")
                return
        if (
            self._portfolio_client_factory is None
            or "portfolio_holdings" not in capabilities
        ):
            self._set_status(
                MoomooConnectionStatus(
                    state="connected",
                    account_count=len(tokens.account_ids),
                    position_count=0,
                    sync_state="unavailable",
                    error_code=None,
                    capabilities=capabilities,
                )
            )
            return
        try:
            client = self._portfolio_client_factory(tokens.access_token)
            accounts, positions = self._load_holdings(
                client,
                expected_account_ids=tokens.account_ids,
            )
        except (OSError, RuntimeError, ValueError):
            self._set_status(
                MoomooConnectionStatus(
                    state="connected",
                    account_count=len(tokens.account_ids),
                    position_count=0,
                    sync_state="failed",
                    error_code="moomoo_holdings_sync_failed",
                    capabilities=capabilities,
                )
            )
            return
        with self._lock:
            self._mirror = MoomooHoldingsMirror(
                accounts=accounts,
                positions=positions,
                sync_state="ready",
            )
            self._operator_id = operator_id
        self._set_status(
            MoomooConnectionStatus(
                state="connected",
                account_count=len(tokens.account_ids),
                position_count=len(positions),
                sync_state="ready",
                error_code=None,
                capabilities=capabilities,
            )
        )

    def _refresh_quote_access(
        self,
        *,
        operator_id: str,
        client_id: str,
    ) -> MoomooQuoteAccess:
        keychain = self._keychain_factory(operator_id)
        refresh_token = keychain.read_refresh_token()
        refreshed = refresh_access_token(
            client_id=client_id,
            refresh_token=refresh_token,
            required_read_scopes=READ_ONLY_SCOPES,
            transport=self._oauth_transport,
        )
        if refreshed.refresh_token is not None:
            keychain.store_refresh_token(refreshed.refresh_token)
        if "quote:read" not in refreshed.read_scopes:
            raise MoomooOAuthError("Moomoo quote read scope was removed")
        with self._lock:
            if self._operator_id != operator_id or self._client_id != client_id:
                raise RuntimeError("Moomoo connection changed")
            self._access_token = refreshed.access_token
        return MoomooQuoteAccess(
            access_token=refreshed.access_token,
            expires_in=refreshed.expires_in,
        )

    @staticmethod
    def _load_holdings(
        client: MoomooPortfolioClient,
        *,
        expected_account_ids: tuple[str, ...],
    ) -> tuple[tuple[MoomooAccount, ...], tuple[MoomooPosition, ...]]:
        accounts = client.list_accounts()
        if tuple(sorted(account.account_id for account in accounts)) != tuple(
            sorted(expected_account_ids)
        ):
            raise RuntimeError("Moomoo authorized account mismatch")
        positions = tuple(
            position
            for account in accounts
            for position in client.list_positions(account.account_id)
        )
        return accounts, positions

    @staticmethod
    def _consume_failed_attempt(attempt: PkceAuthorizationAttempt) -> None:
        try:
            attempt.consume_verifier("")
        except MoomooOAuthError:
            pass

    def _set_failed(self, error_code: str) -> None:
        with self._lock:
            self._pending_operator_id = None
            self._access_token = None
            self._status = MoomooConnectionStatus(
                state="failed",
                account_count=0,
                position_count=0,
                sync_state="failed",
                error_code=error_code,
            )
        self._record_diagnostic(
            subsystem="optional_stream", stage="failed", reason_code=error_code
        )

    def _set_resume_failed(self, *, operator_id: str, error_code: str) -> None:
        with self._lock:
            if (
                self._status.state != "pending"
                or self._pending_operator_id != operator_id
            ):
                return
            self._pending_operator_id = None
            self._access_token = None
            self._status = MoomooConnectionStatus(
                state="failed",
                account_count=0,
                position_count=0,
                sync_state="failed",
                error_code=error_code,
            )
        self._record_diagnostic(
            subsystem="optional_stream", stage="failed", reason_code=error_code
        )

    def _set_status(self, status: MoomooConnectionStatus) -> None:
        with self._lock:
            self._status = status

    def _set_mcp_status(self, status: MoomooMcpDiscoveryStatus) -> None:
        with self._lock:
            self._mcp_status = status
            if status.state not in {"authorizing", "refreshing", "discovering"}:
                self._mcp_pending_operator_id = None
        self._record_diagnostic(
            subsystem="core_mcp",
            stage=status.state,
            reason_code=status.error_code or status.state,
        )

    def _set_mcp_failed(self, error_code: str, *, state: str = "failed") -> None:
        with self._lock:
            self._mcp_access_token = None
            self._mcp_pending_operator_id = None
            self._mcp_status = MoomooMcpDiscoveryStatus(
                state=state,
                tool_count=0,
                error_code=error_code,
            )
        self._record_diagnostic(
            subsystem="core_mcp", stage=state, reason_code=error_code
        )

    def _record_diagnostic(
        self,
        *,
        subsystem: str,
        stage: str,
        reason_code: str,
        shape: MoomooResultShape | None = None,
    ) -> None:
        if self._diagnostics_log is None:
            return
        try:
            self._diagnostics_log.record(
                subsystem=subsystem,
                stage=stage,
                reason_code=reason_code,
                shape=shape,
            )
        except ValueError:
            pass

    @staticmethod
    def _mcp_authorization_required_status() -> MoomooMcpDiscoveryStatus:
        return MoomooMcpDiscoveryStatus(
            state="unavailable",
            tool_count=0,
            error_code="moomoo_mcp_authorization_required",
        )


def _granted_capabilities(
    *,
    read_scopes: tuple[str, ...],
    account_ids: tuple[str, ...],
) -> tuple[str, ...]:
    capabilities: list[str] = []
    if "quote:read" in read_scopes:
        capabilities.append("market_data")
    if "trade:read" in read_scopes and account_ids:
        capabilities.append("portfolio_holdings")
    return tuple(capabilities)


def _summarize_mcp_tools(
    advertised: object,
) -> tuple[Mapping[str, str], ...]:
    if not isinstance(advertised, list):
        raise ValueError("Moomoo MCP tool manifest is invalid")
    summaries: list[Mapping[str, str]] = []
    names: set[str] = set()
    for tool in advertised:
        if not isinstance(tool, Mapping):
            raise ValueError("Moomoo MCP tool entry is invalid")
        name = tool.get("name")
        schema = tool.get("inputSchema", tool.get("input_schema", {}))
        if not isinstance(name, str) or not name.strip() or not isinstance(schema, Mapping):
            raise ValueError("Moomoo MCP tool metadata is invalid")
        normalized_name = name.strip()
        if normalized_name in names:
            raise ValueError("Moomoo MCP tool manifest contains duplicates")
        names.add(normalized_name)
        schema_bytes = json.dumps(
            schema,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        summaries.append(
            {
                "name": normalized_name,
                "input_schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
            }
        )
    return tuple(sorted(summaries, key=lambda item: item["name"]))


def _oauth_failure_code(error: MoomooOAuthError) -> str:
    message = str(error)
    if message == "Moomoo OAuth token exchange failed":
        return "moomoo_token_exchange_failed"
    if message == "Moomoo OAuth token response is invalid":
        return "moomoo_token_response_invalid"
    if message == "Moomoo OAuth token response is too large":
        return "moomoo_token_response_too_large"
    scope_error_prefix = "Moomoo OAuth granted scope mismatch:"
    if message.startswith(scope_error_prefix):
        reason_code = message.removeprefix(scope_error_prefix)
        if reason_code in {
            "missing_required_read_scope",
            "concrete_account_scope_missing",
            "wildcard_account_scope_not_permitted",
            "write_scope_not_permitted",
            "unknown_scope_not_permitted",
        }:
            return f"moomoo_{reason_code}"
        return "moomoo_scope_validation_failed"
    if message == "Moomoo OAuth granted scope mismatch":
        return "moomoo_scope_validation_failed"
    if message == "Moomoo OAuth state mismatch":
        return "moomoo_callback_state_invalid"
    return "moomoo_oauth_protocol_failed"


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        code_values = query.get("code", [])
        state_values = query.get("state", [])
        valid = (
            parsed.path == "/callback"
            and len(code_values) == 1
            and len(state_values) == 1
            and bool(code_values[0])
            and bool(state_values[0])
        )
        if valid:
            self.server.oauth_callback = {  # type: ignore[attr-defined]
                "code": code_values[0],
                "state": state_values[0],
            }
            body = b"Authorization received. Return to Investment Research OS."
            status = 200
        else:
            self.server.oauth_callback = {}  # type: ignore[attr-defined]
            body = b"Authorization failed. Return to Investment Research OS."
            status = 400
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        del args


class DesktopControlServer:
    def __init__(
        self,
        *,
        service: MoomooConnectionService,
        control_token: str,
        research_capture_catalog: DesktopResearchCaptureCatalog | None = None,
        security_registry: DesktopSecurityRegistry | None = None,
        research_notebook: DesktopResearchNotebook | None = None,
        research_capture_import_service: DesktopCaptureImportService | None = None,
        quant_service: DesktopQuantService | None = None,
    ) -> None:
        if not control_token:
            raise ValueError("Desktop control token is required")
        self._service = service
        self._quant_service = quant_service
        self._research_capture_catalog = research_capture_catalog
        self._security_registry = security_registry
        self._research_notebook = research_notebook
        self._research_capture_import_service = research_capture_import_service
        self._control_token = control_token
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_type())
        self._thread: threading.Thread | None = None

    @property
    def origin(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Desktop control server already started")
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="iros-desktop-control",
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            self._server.server_close()
            return
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
        self._thread = None

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        service = self._service
        research_capture_catalog = self._research_capture_catalog
        security_registry = self._security_registry
        research_notebook = self._research_notebook
        research_capture_import_service = self._research_capture_import_service
        quant_service = self._quant_service
        expected_token = self._control_token

        class Handler(BaseHTTPRequestHandler):
            def _authorized(self) -> bool:
                prefix = "Bearer "
                value = self.headers.get("Authorization", "")
                return value.startswith(prefix) and hmac.compare_digest(
                    value.removeprefix(prefix),
                    expected_token,
                )

            def _send_json(self, status: int, payload: Mapping[str, object]) -> None:
                body = json.dumps(
                    payload,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                self.send_response(status)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def _require_authorization(self) -> bool:
                if self._authorized():
                    return True
                self._send_json(401, {"error": "desktop_control_unauthorized"})
                return False

            def do_GET(self) -> None:  # noqa: N802
                if not self._require_authorization():
                    return
                parsed = urlsplit(self.path)
                if parsed.path == "/v1/research/captures":
                    if research_capture_catalog is None:
                        self._send_json(
                            503,
                            {"error": "research_capture_catalog_unavailable"},
                        )
                        return
                    try:
                        query = parse_qs(parsed.query, keep_blank_values=True)
                        required = {
                            "operator_id",
                            "security_id",
                        }
                        optional = {
                            "question_type_version",
                            "workflow_config_version",
                            "as_of_cutoff",
                        }
                        if (
                            not required <= set(query)
                            or not set(query) <= required | optional
                            or any(
                                len(query[field]) != 1 or not query[field][0]
                                for field in query
                            )
                        ):
                            raise ValueError
                        operator_id = str(uuid.UUID(query["operator_id"][0]))
                        security_id = str(uuid.UUID(query["security_id"][0]))
                        cutoff_value = query.get("as_of_cutoff")
                        cutoff = None
                        if cutoff_value is not None:
                            cutoff = datetime.fromisoformat(
                                cutoff_value[0].replace("Z", "+00:00")
                            )
                            if cutoff.tzinfo is None or cutoff.utcoffset() is None:
                                raise ValueError
                        catalog = research_capture_catalog.list_captures(
                            operator_id=operator_id,
                            security_id=security_id,
                            question_type_version=(
                                query.get("question_type_version", [None])[0]
                            ),
                            workflow_config_version=(
                                query.get("workflow_config_version", [None])[0]
                            ),
                            as_of_cutoff=cutoff,
                            max_count=50,
                        )
                    except (OSError, TypeError, ValueError):
                        self._send_json(
                            400,
                            {"error": "research_capture_request_invalid"},
                        )
                        return
                    self._send_json(200, catalog.as_dict())
                    return
                if parsed.path == "/v1/security-registry":
                    if security_registry is None:
                        self._send_json(
                            503,
                            {"error": "security_registry_unavailable"},
                        )
                        return
                    self._send_json(
                        200,
                        {"entries": list(security_registry.list_entries())},
                    )
                    return
                if parsed.path == "/v1/research/notebook":
                    if research_notebook is None:
                        self._send_json(
                            503,
                            {"error": "ticker_notebook_unavailable"},
                        )
                        return
                    try:
                        query = parse_qs(parsed.query, keep_blank_values=True)
                        required = {"security_id"}
                        optional = {"order"}
                        if (
                            not required <= set(query)
                            or not set(query) <= required | optional
                            or any(
                                len(query[field]) != 1 or not query[field][0]
                                for field in query
                            )
                        ):
                            raise TickerNotebookError("ticker notebook request is invalid")
                        security_id = query["security_id"][0]
                        order = query.get("order", ["newest"])[0]
                        notes = research_notebook.list_notes(
                            security_id, order=order
                        )
                    except TickerNotebookError:
                        self._send_json(
                            400,
                            {"error": "ticker_notebook_request_invalid"},
                        )
                        return
                    self._send_json(
                        200,
                        {
                            "contract_version": "ticker_notebook_list.v1",
                            "notes": list(notes),
                            "order": order,
                        },
                    )
                    return
                if parsed.path == "/v1/research/market-evidence/quote":
                    try:
                        query = parse_qs(parsed.query, keep_blank_values=True)
                        if set(query) != {"security_id"} or len(query["security_id"]) != 1:
                            raise ValueError
                        status = service.last_market_quote(
                            security_id=query["security_id"][0]
                        )
                    except (DesktopControlError, ValueError):
                        self._send_json(
                            400,
                            {"error": "moomoo_market_evidence_request_invalid"},
                        )
                        return
                    self._send_json(
                        200,
                        {
                            "contract_version": "market_quote_evidence.v1",
                            **status.as_dict(),
                        },
                    )
                    return
                if parsed.path in ("/v1/quant/dataset", "/v1/quant/runs/latest"):
                    if quant_service is None:
                        self._send_json(503, {"error": "quant_workspace_unavailable"})
                        return
                    try:
                        query = parse_qs(parsed.query, keep_blank_values=True)
                        if set(query) != {"operator_id", "security_id"} or any(
                            len(query[field]) != 1 for field in query
                        ):
                            raise ValueError
                        operator_id = str(uuid.UUID(query["operator_id"][0]))
                        security_id = str(uuid.UUID(query["security_id"][0]))
                        if parsed.path == "/v1/quant/dataset":
                            status: Mapping[str, object] = quant_service.dataset_status(
                                operator_id=operator_id,
                                security_id=security_id,
                            )
                        else:
                            status = {
                                "result": quant_service.latest_result(
                                    operator_id=operator_id,
                                    security_id=security_id,
                                )
                            }
                    except (ValueError, QuantWorkspaceError) as error:
                        self._send_json(
                            400,
                            {
                                "error": "quant_request_invalid",
                                "reason": getattr(error, "code", "quant_request_invalid"),
                            },
                        )
                        return
                    self._send_json(200, dict(status))
                    return
                if self.path == "/v1/moomoo/status":
                    self._send_json(200, service.status().as_dict())
                    return
                if self.path == "/v1/moomoo/mcp/status":
                    self._send_json(200, service.mcp_discovery_status().as_dict())
                    return
                if self.path == "/v1/moomoo/diagnostics":
                    self._send_json(
                        200,
                        {
                            "contract_version": "moomoo_diagnostics.v1",
                            "entries": service.recent_diagnostics(),
                        },
                    )
                    return
                if self.path == "/v1/moomoo/holdings":
                    self._send_json(200, service.holdings().as_dict())
                    return
                if self.path == "/v1/moomoo/quotes":
                    self._send_json(200, service.quotes().as_dict())
                    return
                self._send_json(404, {"error": "desktop_control_not_found"})

            def do_POST(self) -> None:  # noqa: N802
                if not self._require_authorization():
                    return
                if self.path not in {
                    "/v1/moomoo/compose",
                    "/v1/moomoo/connect",
                    "/v1/moomoo/disconnect",
                    "/v1/moomoo/mcp/connect",
                    "/v1/moomoo/mcp/discover",
                    "/v1/moomoo/mcp/resume",
                    "/v1/moomoo/mcp/disconnect",
                    "/v1/moomoo/mcp/holdings/refresh",
                    "/v1/moomoo/disconnect-all",
                    "/v1/moomoo/refresh",
                    "/v1/moomoo/resume",
                    "/v1/moomoo/quotes/subscriptions",
                    "/v1/security-registry",
                    "/v1/security-registry/import-moomoo",
                    "/v1/research/notebook",
                    "/v1/research/captures/import",
                    "/v1/research/market-evidence/quote",
                    "/v1/research/market-evidence/history",
                    "/v1/quant/dataset/import",
                    "/v1/quant/runs",
                }:
                    self._send_json(404, {"error": "desktop_control_not_found"})
                    return
                length = self.headers.get("Content-Length", "")
                try:
                    content_length = int(length)
                except ValueError:
                    self._send_json(400, {"error": "desktop_control_body_invalid"})
                    return
                if content_length <= 0 or content_length > MAX_CONTROL_BODY_BYTES:
                    self._send_json(400, {"error": "desktop_control_body_invalid"})
                    return
                try:
                    body = json.loads(self.rfile.read(content_length))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send_json(400, {"error": "desktop_control_body_invalid"})
                    return
                if not isinstance(body, Mapping):
                    self._send_json(400, {"error": "desktop_control_body_invalid"})
                    return
                if self.path == "/v1/security-registry":
                    if security_registry is None:
                        self._send_json(
                            503,
                            {"error": "security_registry_unavailable"},
                        )
                        return
                    try:
                        if set(body) != {"ticker"}:
                            raise ValueError
                        security_registry.add_manual_ticker(str(body["ticker"]))
                    except ValueError:
                        self._send_json(
                            400,
                            {"error": "security_registry_request_invalid"},
                        )
                        return
                    self._send_json(200, {"entries": list(security_registry.list_entries())})
                    return
                if self.path == "/v1/security-registry/import-moomoo":
                    if security_registry is None:
                        self._send_json(
                            503,
                            {"error": "security_registry_unavailable"},
                        )
                        return
                    try:
                        if body:
                            raise ValueError
                        mirror = service.holdings().as_dict()
                        positions = mirror.get("positions")
                        if not isinstance(positions, list):
                            raise ValueError
                        symbols = tuple(
                            position["code"]
                            for position in positions
                            if isinstance(position, Mapping)
                            and isinstance(position.get("code"), str)
                        )
                        security_registry.import_moomoo_symbols(symbols)
                    except (AttributeError, ValueError):
                        self._send_json(
                            400,
                            {"error": "security_registry_import_invalid"},
                        )
                        return
                    self._send_json(200, {"entries": list(security_registry.list_entries())})
                    return
                if self.path == "/v1/research/notebook":
                    if research_notebook is None:
                        self._send_json(
                            503,
                            {"error": "ticker_notebook_unavailable"},
                        )
                        return
                    try:
                        if set(body) != {"security_id", "body"}:
                            raise TickerNotebookError("ticker notebook request is invalid")
                        note = research_notebook.add_note(
                            str(body["security_id"]), str(body["body"])
                        )
                    except TickerNotebookError:
                        self._send_json(
                            400,
                            {"error": "ticker_notebook_request_invalid"},
                        )
                        return
                    self._send_json(
                        200,
                        {"contract_version": "ticker_notebook_note.v1", **note},
                    )
                    return
                if self.path in ("/v1/quant/dataset/import", "/v1/quant/runs"):
                    if quant_service is None:
                        self._send_json(503, {"error": "quant_workspace_unavailable"})
                        return
                    importing = self.path == "/v1/quant/dataset/import"
                    try:
                        required = {"operator_id", "security_id"} | (
                            {"dataset_path"} if importing else {"assumptions"}
                        )
                        if set(body) != required:
                            raise ValueError
                        operator_id = str(uuid.UUID(str(body["operator_id"])))
                        security_id = str(uuid.UUID(str(body["security_id"])))
                        if importing:
                            payload: Mapping[str, object] = quant_service.import_dataset(
                                operator_id=operator_id,
                                security_id=security_id,
                                dataset_path=Path(str(body["dataset_path"])),
                            )
                        else:
                            assumptions = body["assumptions"]
                            if not isinstance(assumptions, Mapping):
                                raise ValueError
                            payload = quant_service.run_analysis(
                                operator_id=operator_id,
                                security_id=security_id,
                                assumptions=assumptions,
                            )
                    except (ValueError, TypeError, QuantWorkspaceError) as error:
                        self._send_json(
                            400,
                            {
                                "error": "quant_request_invalid",
                                "reason": getattr(error, "code", "quant_request_invalid"),
                            },
                        )
                        return
                    self._send_json(200, dict(payload))
                    return
                if self.path == "/v1/research/captures/import":
                    if research_capture_import_service is None:
                        self._send_json(
                            503,
                            {"error": "primary_source_capture_import_unavailable"},
                        )
                        return
                    try:
                        required_fields = {
                            "operator_id",
                            "security_id",
                            "cik",
                            "issuer_name",
                            "primary_listing_exchange",
                            "as_of_cutoff",
                            "archive_path",
                            "trusted_issuer_hosts",
                        }
                        if set(body) != required_fields:
                            raise DesktopCaptureImportError(
                                "capture import request is invalid"
                            )
                        cutoff = datetime.fromisoformat(
                            str(body["as_of_cutoff"]).replace("Z", "+00:00")
                        )
                        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
                            raise DesktopCaptureImportError(
                                "capture import cutoff is invalid"
                            )
                        hosts = body["trusted_issuer_hosts"]
                        if not isinstance(hosts, list) or not all(
                            isinstance(host, str) for host in hosts
                        ):
                            raise DesktopCaptureImportError(
                                "capture import trusted issuer hosts are invalid"
                            )
                        persisted = research_capture_import_service.import_capture(
                            DesktopCaptureImportRequest(
                                operator_id=str(body["operator_id"]),
                                security_id=str(body["security_id"]),
                                cik=str(body["cik"]),
                                issuer_name=str(body["issuer_name"]),
                                primary_listing_exchange=str(
                                    body["primary_listing_exchange"]
                                ),
                                as_of_cutoff=cutoff,
                                archive_path=Path(str(body["archive_path"])),
                                trusted_issuer_hosts=tuple(hosts),
                            )
                        )
                    except (
                        DesktopCaptureImportError,
                        ValueError,
                        TypeError,
                    ) as error:
                        self._send_json(
                            400,
                            {
                                "error": "primary_source_capture_import_invalid",
                                "reason": str(error),
                            },
                        )
                        return
                    entry = AcceptedCaptureCatalogEntry(
                        capture_id=persisted.capture_id,
                        capture_revision=persisted.capture_revision,
                        capture_content_hash=persisted.capture_content_hash,
                        as_of_cutoff=persisted.as_of_cutoff,
                        question_type=persisted.question_type,
                        question_type_version=persisted.question_type_version,
                        workflow_config_version=persisted.workflow_config_version,
                        accepted_at=persisted.accepted_at,
                    )
                    self._send_json(
                        200,
                        {
                            "contract_version": "primary_source_capture_import_receipt.v1",
                            **entry.as_dict(),
                        },
                    )
                    return
                if self.path == "/v1/research/market-evidence/quote":
                    try:
                        if set(body) != {"operator_id", "security_id", "ticker"}:
                            raise ValueError
                        status = service.fetch_market_quote(
                            operator_id=str(body["operator_id"]),
                            security_id=str(body["security_id"]),
                            ticker=str(body["ticker"]),
                        )
                    except ValueError:
                        self._send_json(
                            400,
                            {"error": "moomoo_market_evidence_request_invalid"},
                        )
                        return
                    except DesktopControlError as error:
                        http_status = (
                            409
                            if error.code
                            in {
                                "moomoo_mcp_discovery_requires_connection",
                                "moomoo_mcp_discovery_required",
                            }
                            else 400
                        )
                        self._send_json(http_status, {"error": error.code})
                        return
                    self._send_json(
                        200,
                        {
                            "contract_version": "market_quote_evidence.v1",
                            **status.as_dict(),
                        },
                    )
                    return
                if self.path == "/v1/research/market-evidence/history":
                    try:
                        if set(body) != {
                            "end",
                            "max_bars",
                            "operator_id",
                            "security_id",
                            "start",
                            "ticker",
                        }:
                            raise ValueError
                        max_bars = body["max_bars"]
                        if isinstance(max_bars, bool) or not isinstance(max_bars, int):
                            raise ValueError
                        status = service.fetch_market_history(
                            operator_id=str(body["operator_id"]),
                            security_id=str(body["security_id"]),
                            ticker=str(body["ticker"]),
                            start=str(body["start"]),
                            end=str(body["end"]),
                            max_bars=max_bars,
                        )
                    except ValueError:
                        self._send_json(
                            400, {"error": "moomoo_market_history_request_invalid"}
                        )
                        return
                    except DesktopControlError as error:
                        http_status = (
                            409
                            if error.code
                            in {
                                "moomoo_mcp_discovery_requires_connection",
                                "moomoo_mcp_discovery_required",
                            }
                            else 400
                        )
                        self._send_json(http_status, {"error": error.code})
                        return
                    self._send_json(
                        200,
                        {
                            "contract_version": "market_history_evidence.v1",
                            **status.as_dict(),
                        },
                    )
                    return
                if self.path == "/v1/moomoo/connect":
                    try:
                        status = service.start_connection(
                            client_id=str(body.get("client_id", "")),
                            operator_id=str(body.get("operator_id", "")),
                            redirect_uri=str(body.get("redirect_uri", "")),
                        )
                    except DesktopControlError as error:
                        http_status = (
                            409
                            if error.code == "moomoo_connection_already_pending"
                            else 400
                        )
                        self._send_json(http_status, {"error": error.code})
                        return
                    self._send_json(202, status.as_dict())
                    return
                if self.path == "/v1/moomoo/mcp/holdings/refresh":
                    if set(body) != {"operator_id"}:
                        self._send_json(
                            400, {"error": "moomoo_mcp_portfolio_request_invalid"}
                        )
                        return
                    try:
                        mirror = service.refresh_mcp_holdings(
                            operator_id=str(body["operator_id"])
                        )
                    except DesktopControlError as error:
                        self._send_json(409, {"error": error.code})
                        return
                    self._send_json(200, mirror.as_dict())
                    return
                if self.path == "/v1/moomoo/mcp/discover":
                    if set(body) != {"operator_id"}:
                        self._send_json(400, {"error": "moomoo_mcp_discovery_request_invalid"})
                        return
                    try:
                        status = service.discover_mcp_tools(
                            operator_id=str(body["operator_id"]),
                        )
                    except DesktopControlError as error:
                        http_status = (
                            409
                            if error.code == "moomoo_mcp_discovery_requires_connection"
                            else 400
                        )
                        self._send_json(http_status, {"error": error.code})
                        return
                    self._send_json(200, status.as_dict())
                    return
                if self.path == "/v1/moomoo/mcp/connect":
                    if set(body) != {"operator_id", "redirect_uri"}:
                        self._send_json(
                            400,
                            {"error": "moomoo_mcp_authorization_request_invalid"},
                        )
                        return
                    try:
                        status = service.start_mcp_authorization(
                            operator_id=str(body["operator_id"]),
                            redirect_uri=str(body["redirect_uri"]),
                        )
                    except DesktopControlError as error:
                        http_status = (
                            409
                            if error.code == "moomoo_mcp_authorization_already_pending"
                            else 400
                        )
                        self._send_json(http_status, {"error": error.code})
                        return
                    self._send_json(202, status.as_dict())
                    return
                if self.path == "/v1/moomoo/resume":
                    try:
                        status = service.resume_connection(
                            client_id=str(body.get("client_id", "")),
                            operator_id=str(body.get("operator_id", "")),
                        )
                    except DesktopControlError as error:
                        http_status = (
                            409
                            if error.code == "moomoo_connection_already_pending"
                            else 400
                        )
                        self._send_json(http_status, {"error": error.code})
                        return
                    self._send_json(200, status.as_dict())
                    return
                if self.path == "/v1/moomoo/mcp/resume":
                    if set(body) != {"operator_id"}:
                        self._send_json(
                            400, {"error": "moomoo_mcp_resume_request_invalid"}
                        )
                        return
                    try:
                        status = service.resume_mcp_connection(
                            operator_id=str(body["operator_id"]),
                        )
                    except DesktopControlError as error:
                        self._send_json(400, {"error": error.code})
                        return
                    self._send_json(200, status.as_dict())
                    return
                if self.path == "/v1/moomoo/mcp/disconnect":
                    if set(body) != {"operator_id"}:
                        self._send_json(
                            400, {"error": "moomoo_mcp_disconnect_request_invalid"}
                        )
                        return
                    try:
                        status = service.disconnect_mcp(
                            operator_id=str(body["operator_id"])
                        )
                    except DesktopControlError as error:
                        self._send_json(400, {"error": error.code})
                        return
                    self._send_json(200, status.as_dict())
                    return
                if self.path == "/v1/moomoo/disconnect-all":
                    if set(body) != {"operator_id"}:
                        self._send_json(
                            400, {"error": "moomoo_disconnect_all_request_invalid"}
                        )
                        return
                    try:
                        service.disconnect_all(
                            operator_id=str(body["operator_id"])
                        )
                    except DesktopControlError as error:
                        self._send_json(400, {"error": error.code})
                        return
                    self._send_json(200, {"state": "disconnected"})
                    return
                if self.path == "/v1/moomoo/compose":
                    try:
                        checked_at = datetime.fromisoformat(
                            str(body.get("checked_at", ""))
                        )
                        if checked_at.tzinfo is None:
                            raise ValueError
                        composition = service.compose_holdings(
                            operator_id=str(body.get("operator_id", "")),
                            candidates=_parse_security_candidates(
                                body.get("candidates")
                            ),
                            checked_at=checked_at,
                        )
                    except (TypeError, ValueError):
                        self._send_json(
                            400,
                            {"error": "moomoo_compose_request_invalid"},
                        )
                        return
                    except DesktopControlError as error:
                        self._send_json(400, {"error": error.code})
                        return
                    self._send_json(200, composition.as_dict())
                    return
                if self.path == "/v1/moomoo/disconnect":
                    try:
                        status = service.disconnect(
                            operator_id=str(body.get("operator_id", ""))
                        )
                    except DesktopControlError as error:
                        self._send_json(400, {"error": error.code})
                        return
                    self._send_json(200, status.as_dict())
                    return
                if self.path == "/v1/moomoo/refresh":
                    try:
                        status = service.refresh_holdings(
                            operator_id=str(body.get("operator_id", "")),
                        )
                    except DesktopControlError as error:
                        self._send_json(400, {"error": error.code})
                        return
                    self._send_json(200, status.as_dict())
                    return
                if self.path == "/v1/moomoo/quotes/subscriptions":
                    symbols = body.get("symbols")
                    if not isinstance(symbols, list) or not all(
                        isinstance(symbol, str) for symbol in symbols
                    ):
                        self._send_json(
                            400,
                            {"error": "moomoo_quote_subscription_invalid"},
                        )
                        return
                    try:
                        quote_status = service.replace_quote_symbols(
                            operator_id=str(body.get("operator_id", "")),
                            symbols=tuple(symbols),
                        )
                    except DesktopControlError as error:
                        self._send_json(400, {"error": error.code})
                        return
                    self._send_json(200, quote_status.as_dict())
                    return

            def log_message(self, _format: str, *args: object) -> None:
                del args

        return Handler


def _parse_security_candidates(value: object) -> tuple[DesktopSecurityCandidate, ...]:
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("portfolio security candidates are invalid")
    candidates: list[DesktopSecurityCandidate] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {
            "security_id",
            "ticker",
            "primary_listing_exchange",
        }:
            raise ValueError("portfolio security candidate is invalid")
        security_id = str(uuid.UUID(str(item["security_id"])))
        ticker = str(item["ticker"]).strip().upper()
        exchange = str(item["primary_listing_exchange"]).strip().upper()
        if not ticker or not exchange:
            raise ValueError("portfolio security candidate is invalid")
        candidates.append(
            DesktopSecurityCandidate(
                security_id=security_id,
                ticker=ticker,
                primary_listing_exchange=exchange,
            )
        )
    return tuple(candidates)
