from __future__ import annotations

import json
import inspect
import os
from pathlib import Path
import subprocess
import sys
import unittest
from http.client import HTTPConnection
from urllib.parse import urlsplit

from workers.desktop.__main__ import (
    _build_moomoo_portfolio_client,
    _research_capture_root,
)
from workers.desktop import __main__ as desktop_main
from workers.portfolio.moomoo import UrllibMoomooTransport


class DesktopWorkerTests(unittest.TestCase):
    def test_research_capture_root_is_stable_and_override_must_be_absolute(
        self,
    ) -> None:
        self.assertEqual(
            _research_capture_root({}, packaged=True),
            Path.home()
            / "Library"
            / "Application Support"
            / "Investment Research OS"
            / "primary-source-captures",
        )
        self.assertEqual(
            _research_capture_root({}, packaged=False),
            Path.cwd() / "data" / "primary-source-captures",
        )
        self.assertEqual(
            _research_capture_root(
                {"IROS_PRIMARY_SOURCE_CAPTURE_ROOT": "/tmp/iros-captures"}
            ),
            Path("/tmp/iros-captures"),
        )
        with self.assertRaisesRegex(ValueError, "must be absolute"):
            _research_capture_root(
                {"IROS_PRIMARY_SOURCE_CAPTURE_ROOT": "relative/captures"}
            )

    def test_desktop_build_scrubs_service_credentials_before_packaging(self) -> None:
        build_script = Path("scripts/build-desktop-app.sh").read_text()

        scrub_index = build_script.index("unset IROS_SUPABASE_SECRET_KEY")
        package_index = build_script.index("deno desktop")
        self.assertLess(scrub_index, package_index)
        self.assertIn(
            "SUPABASE_SERVICE_ROLE_KEY", build_script[scrub_index:package_index]
        )

    def test_packaged_worker_has_no_supabase_persistence_credential_surface(
        self,
    ) -> None:
        source = inspect.getsource(desktop_main)

        self.assertNotIn("IROS_SUPABASE_SECRET_KEY", source)
        self.assertNotIn("IROS_SUPABASE_URL", source)
        self.assertNotIn("SupabasePortfolioStore", source)
        self.assertNotIn("SupabaseStorageSettings", source)

    def test_runtime_composes_official_read_only_moomoo_client(self) -> None:
        client = _build_moomoo_portfolio_client("access-secret")

        self.assertEqual(client.settings.scopes, ("quote:read", "trade:read"))
        self.assertEqual(client.settings.success_indicator, "ok")
        self.assertIsInstance(client.transport, UrllibMoomooTransport)
        self.assertNotIn("access-secret", repr(client))

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

        self.assertEqual(ready["contract_version"], "desktop_worker_status.v1")
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(ready["worker_id"], "iros-desktop-worker")
        self.assertRegex(ready["control_origin"], r"^http://127\.0\.0\.1:\d+$")
        self.assertTrue(ready["control_token"])

        parsed = urlsplit(ready["control_origin"])
        connection = HTTPConnection(parsed.hostname, parsed.port, timeout=1)
        connection.request(
            "GET",
            "/v1/moomoo/status",
            headers={"Authorization": f"Bearer {ready['control_token']}"},
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.read())["state"], "disconnected")

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
