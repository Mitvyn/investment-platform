from __future__ import annotations

import json
import os
import secrets
import signal
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from workers.desktop.control import DesktopControlServer, MoomooConnectionService
from workers.desktop.research import DesktopResearchCaptureCatalog
from workers.desktop.research_capture_import import DesktopCaptureImportService
from workers.desktop.research_notebook import DesktopResearchNotebook
from workers.desktop.research_run import DesktopResearchRunService
from workers.desktop.security_registry import DesktopSecurityRegistry
from workers.market.client import YFinanceSettings
from workers.quant_sources.live import (
    YFinanceHistoryTransport,
    yfinance_end_exclusive_policy,
)
from workers.quant_sources.workspace_bridge import ProviderQuantWorkspaceBridge
from workers.quant_workspace.service import DesktopQuantService
from workers.quant_workspace.storage import FileQuantWorkspaceStore
from workers.moomoo_mcp.client_identity import MoomooMcpClientIdentityStore
from workers.moomoo_mcp.diagnostics import MoomooDiagnosticsLog
from workers.moomoo_mcp.http_client import MoomooMcpHttpClient
from workers.moomoo_mcp.keychain import MoomooMcpTokenKeychain
from workers.moomoo_mcp.oauth import UrllibMoomooMcpOAuthTransport
from workers.primary_sources.storage import FilePrimarySourceCaptureRepository
from workers.portfolio.keychain import MoomooTokenKeychain
from workers.portfolio.moomoo import (
    MoomooClient,
    MoomooSettings,
    UrllibMoomooTransport,
)
from workers.portfolio.oauth import UrllibMoomooOAuthTransport
from workers.portfolio.quote_stream import MoomooQuoteStream


def _build_moomoo_portfolio_client(access_token: str) -> MoomooClient:
    return MoomooClient(
        MoomooSettings(scopes=("quote:read", "trade:read")),
        access_token=access_token,
        transport=UrllibMoomooTransport(),
    )


def _parent_is_alive(parent_pid: int) -> bool:
    try:
        os.kill(parent_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _research_capture_root(
    environment: Mapping[str, str],
    *,
    packaged: bool = bool(getattr(sys, "frozen", False)),
) -> Path:
    configured = environment.get("IROS_PRIMARY_SOURCE_CAPTURE_ROOT", "").strip()
    if configured:
        root = Path(configured).expanduser()
        if not root.is_absolute():
            raise ValueError("IROS_PRIMARY_SOURCE_CAPTURE_ROOT must be absolute")
        return root
    if packaged:
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Investment Research OS"
            / "primary-source-captures"
        )
    return Path.cwd() / "data" / "primary-source-captures"


def _security_registry_path(
    *,
    packaged: bool = bool(getattr(sys, "frozen", False)),
) -> Path:
    if packaged:
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Investment Research OS"
            / "security-registry.sqlite3"
        )
    return Path.cwd() / "data" / "security-registry.sqlite3"


def _ticker_notebook_path(
    *,
    packaged: bool = bool(getattr(sys, "frozen", False)),
) -> Path:
    if packaged:
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Investment Research OS"
            / "ticker-notebook.sqlite3"
        )
    return Path.cwd() / "data" / "ticker-notebook.sqlite3"


def _quant_workspace_root(
    *,
    packaged: bool = bool(getattr(sys, "frozen", False)),
) -> Path:
    """Where imported Quant datasets and computed results live."""

    if packaged:
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Investment Research OS"
            / "quant-workspace"
        )
    return Path.cwd() / "data" / "quant-workspace"


def _mcp_client_identity_path(
    *,
    packaged: bool = bool(getattr(sys, "frozen", False)),
) -> Path:
    if packaged:
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Investment Research OS"
            / "moomoo-mcp-client-identity.json"
        )
    return Path.cwd() / "data" / "moomoo-mcp-client-identity.json"


def _mcp_diagnostics_path(
    *,
    packaged: bool = bool(getattr(sys, "frozen", False)),
) -> Path:
    if packaged:
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Investment Research OS"
            / "moomoo-diagnostics.json"
        )
    return Path.cwd() / "data" / "moomoo-diagnostics.json"


def _local_research_storage_path(
    name: str,
    *,
    packaged: bool = bool(getattr(sys, "frozen", False)),
) -> Path:
    if packaged:
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Investment Research OS"
            / name
        )
    return Path.cwd() / "data" / name


def run(*, healthcheck: bool = False) -> int:
    if healthcheck:
        print(
            json.dumps(
                {
                    "contract_version": "desktop_worker_status.v1",
                    "state": "ready",
                    "worker_id": "iros-desktop-worker",
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            flush=True,
        )
        return 0

    stop_requested = threading.Event()
    parent_pid_value = os.environ.get("IROS_DESKTOP_PARENT_PID")
    parent_pid = int(parent_pid_value) if parent_pid_value else None

    def request_stop(_signum: int, _frame: object) -> None:
        stop_requested.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    control_token = secrets.token_urlsafe(32)
    capture_repository = FilePrimarySourceCaptureRepository(
        _research_capture_root(os.environ)
    )
    control_server = DesktopControlServer(
        control_token=control_token,
        service=MoomooConnectionService(
            keychain_factory=lambda operator_id: MoomooTokenKeychain(
                operator_id=operator_id
            ),
            oauth_transport=UrllibMoomooOAuthTransport(),
            portfolio_client_factory=_build_moomoo_portfolio_client,
            mcp_client_factory=lambda access_token: MoomooMcpHttpClient(
                access_token=access_token
            ),
            mcp_keychain_factory=lambda operator_id, client_id: MoomooMcpTokenKeychain(
                operator_id=operator_id,
                client_id=client_id,
            ),
            # No env var is required for normal operation: when unset, the
            # service dynamically registers (RFC 7591) a public MCP OAuth
            # client on first connect and persists only the public
            # `client_id` via `mcp_client_identity_store` below. Setting
            # IROS_MOOMOO_MCP_CLIENT_ID remains available as an advanced
            # manual override (e.g. an operator-provisioned client ID) and
            # takes precedence over both dynamic registration and any
            # previously persisted identity.
            mcp_oauth_client_id=os.environ.get("IROS_MOOMOO_MCP_CLIENT_ID") or None,
            mcp_oauth_transport=UrllibMoomooMcpOAuthTransport(),
            mcp_client_identity_store=MoomooMcpClientIdentityStore(
                _mcp_client_identity_path()
            ),
            diagnostics_log=MoomooDiagnosticsLog(path=_mcp_diagnostics_path()),
            quote_stream_factory=lambda access_supplier: MoomooQuoteStream(
                access_supplier=access_supplier
            ),
        ),
        research_capture_catalog=DesktopResearchCaptureCatalog(
            capture_repository
        ),
        security_registry=DesktopSecurityRegistry(_security_registry_path()),
        research_notebook=DesktopResearchNotebook(_ticker_notebook_path()),
        quant_service=DesktopQuantService(
            FileQuantWorkspaceStore(_quant_workspace_root())
        ),
        # The only approved live history transport. Moomoo history has no
        # verified endpoint and is not wired in here; see
        # MOOMOO_HISTORY_BLOCKER in workers/quant_sources/live.py.
        quant_provider_bridge=ProviderQuantWorkspaceBridge(
            FileQuantWorkspaceStore(_quant_workspace_root()),
            transport=YFinanceHistoryTransport(
                YFinanceSettings(),
                window_semantics=yfinance_end_exclusive_policy(),
            ),
        ),
        research_capture_import_service=DesktopCaptureImportService(
            capture_repository,
            clock=lambda: datetime.now(UTC),
        ),
        research_run_service=DesktopResearchRunService(
            capture_repository=capture_repository,
            command_root=_local_research_storage_path("research-run-commands"),
            research_run_root=_local_research_storage_path("research-runs"),
            evidence_bundle_root=_local_research_storage_path("evidence-bundles"),
            sec_user_agent=(
                os.environ.get(
                    "SEC_USER_AGENT",
                    "Investment Research OS local@example.com",
                ).strip()
            ),
            clock=lambda: datetime.now(UTC),
        ),
    )
    control_server.start()
    try:
        print(
            json.dumps(
                {
                    "contract_version": "desktop_worker_status.v1",
                    "control_origin": control_server.origin,
                    "control_token": control_token,
                    "state": "ready",
                    "worker_id": "iros-desktop-worker",
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            flush=True,
        )
        while not stop_requested.wait(timeout=0.25):
            if parent_pid is not None and not _parent_is_alive(parent_pid):
                break
    finally:
        control_server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run(healthcheck=sys.argv[1:] == ["--healthcheck"]))
