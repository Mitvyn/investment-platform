from __future__ import annotations

import hmac
import json
import threading
import uuid
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
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


class MoomooPortfolioClient(Protocol):
    def list_accounts(self) -> tuple[MoomooAccount, ...]: ...

    def list_positions(self, account_id: str) -> tuple[MoomooPosition, ...]: ...


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
        browser_opener: Callable[[str], bool] = webbrowser.open,
        callback_timeout_seconds: float = 180,
    ) -> None:
        if callback_timeout_seconds <= 0:
            raise ValueError("Moomoo callback timeout must be positive")
        self._browser_opener = browser_opener
        self._callback_timeout_seconds = callback_timeout_seconds
        self._keychain_factory = keychain_factory
        self._oauth_transport = oauth_transport
        self._portfolio_client_factory = portfolio_client_factory
        self._quote_stream_factory = quote_stream_factory
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

    def status(self) -> MoomooConnectionStatus:
        with self._lock:
            return self._status

    def holdings(self) -> MoomooHoldingsMirror:
        with self._lock:
            return self._mirror

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
            refresh_token = self._keychain_factory(
                normalized_operator_id
            ).read_refresh_token()
            refreshed = refresh_access_token(
                client_id=client_id,
                refresh_token=refresh_token,
                required_read_scopes=READ_ONLY_SCOPES,
                transport=self._oauth_transport,
            )
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
            refresh_token = self._keychain_factory(
                normalized_operator_id
            ).read_refresh_token()
            refreshed = refresh_access_token(
                client_id=normalized_client_id,
                refresh_token=refresh_token,
                required_read_scopes=READ_ONLY_SCOPES,
                transport=self._oauth_transport,
            )
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
                self._authorized_account_ids = refreshed.account_ids
                self._capabilities = capabilities
                self._quote_stream = quote_stream
                self._status = status
        if connection_changed:
            if quote_stream is not None:
                quote_stream.stop()
            raise DesktopControlError("moomoo_connection_changed")
        return status

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
        refresh_token = self._keychain_factory(operator_id).read_refresh_token()
        refreshed = refresh_access_token(
            client_id=client_id,
            refresh_token=refresh_token,
            required_read_scopes=READ_ONLY_SCOPES,
            transport=self._oauth_transport,
        )
        if "quote:read" not in refreshed.read_scopes:
            raise MoomooOAuthError("Moomoo quote read scope was removed")
        with self._lock:
            if self._operator_id != operator_id or self._client_id != client_id:
                raise RuntimeError("Moomoo connection changed")
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
            self._status = MoomooConnectionStatus(
                state="failed",
                account_count=0,
                position_count=0,
                sync_state="failed",
                error_code=error_code,
            )

    def _set_resume_failed(self, *, operator_id: str, error_code: str) -> None:
        with self._lock:
            if (
                self._status.state != "pending"
                or self._pending_operator_id != operator_id
            ):
                return
            self._pending_operator_id = None
            self._status = MoomooConnectionStatus(
                state="failed",
                account_count=0,
                position_count=0,
                sync_state="failed",
                error_code=error_code,
            )

    def _set_status(self, status: MoomooConnectionStatus) -> None:
        with self._lock:
            self._status = status


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
    ) -> None:
        if not control_token:
            raise ValueError("Desktop control token is required")
        self._service = service
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
                if self.path == "/v1/moomoo/status":
                    self._send_json(200, service.status().as_dict())
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
                    "/v1/moomoo/refresh",
                    "/v1/moomoo/resume",
                    "/v1/moomoo/quotes/subscriptions",
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
