from __future__ import annotations

import json
import os
import signal
import sys
import threading


def _parent_is_alive(parent_pid: int) -> bool:
    try:
        os.kill(parent_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run(*, healthcheck: bool = False) -> int:
    stop_requested = threading.Event()
    parent_pid_value = os.environ.get("IROS_DESKTOP_PARENT_PID")
    parent_pid = int(parent_pid_value) if parent_pid_value else None

    def request_stop(_signum: int, _frame: object) -> None:
        stop_requested.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

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
    if healthcheck:
        return 0
    while not stop_requested.wait(timeout=0.25):
        if parent_pid is not None and not _parent_is_alive(parent_pid):
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(run(healthcheck=sys.argv[1:] == ["--healthcheck"]))
