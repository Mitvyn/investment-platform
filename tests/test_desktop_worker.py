from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest


class DesktopWorkerTests(unittest.TestCase):
    def test_worker_announces_ready_and_stops_cleanly(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-m", "workers.desktop"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())

        assert process.stdout is not None
        ready = json.loads(process.stdout.readline())

        self.assertEqual(
            ready,
            {
                "contract_version": "desktop_worker_status.v1",
                "state": "ready",
                "worker_id": "iros-desktop-worker",
            },
        )

        process.terminate()
        self.assertEqual(process.wait(timeout=3), 0)
        process.stdout.close()
        assert process.stderr is not None
        process.stderr.close()

    def test_worker_exits_when_desktop_parent_disappears(self) -> None:
        parent = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.1)"],
        )
        environment = os.environ.copy()
        environment["IROS_DESKTOP_PARENT_PID"] = str(parent.pid)
        process = subprocess.Popen(
            [sys.executable, "-m", "workers.desktop"],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())

        assert process.stdout is not None
        self.assertEqual(json.loads(process.stdout.readline())["state"], "ready")
        self.assertEqual(parent.wait(timeout=1), 0)
        self.assertEqual(process.wait(timeout=2), 0)
        process.stdout.close()
        assert process.stderr is not None
        process.stderr.close()

    def test_healthcheck_announces_ready_and_exits(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "workers.desktop", "--healthcheck"],
            capture_output=True,
            check=False,
            text=True,
            timeout=1,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "contract_version": "desktop_worker_status.v1",
                "state": "ready",
                "worker_id": "iros-desktop-worker",
            },
        )


if __name__ == "__main__":
    unittest.main()
