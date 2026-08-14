from __future__ import annotations

import json
import os
import secrets
import signal
import sys
import threading

from workers.desktop.control import DesktopControlServer, MoomooConnectionService
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
    control_server = DesktopControlServer(
        control_token=control_token,
        service=MoomooConnectionService(
            keychain_factory=lambda operator_id: MoomooTokenKeychain(
                operator_id=operator_id
            ),
            oauth_transport=UrllibMoomooOAuthTransport(),
            portfolio_client_factory=_build_moomoo_portfolio_client,
            quote_stream_factory=lambda access_supplier: MoomooQuoteStream(
                access_supplier=access_supplier
            ),
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
