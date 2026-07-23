from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from workers.security_onboarding.__main__ import run


class SecurityOnboardingCliTests(unittest.TestCase):
    def test_missing_environment_stops_before_claiming_jobs(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.stderr") as stderr:
                exit_code = run(["run-once"])

        self.assertEqual(exit_code, 2)
        message = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("IROS_WORKER_ID", message)
        self.assertNotIn("secret_key=", message)

    def test_unexpected_worker_error_is_redacted_at_process_boundary(self) -> None:
        class CrashingWorker:
            def run_once(self) -> bool:
                raise RuntimeError("private provider detail")

        with patch(
            "workers.security_onboarding.__main__.build_worker",
            return_value=CrashingWorker(),
        ):
            with patch("sys.stderr") as stderr:
                exit_code = run(["run-once"])

        self.assertEqual(exit_code, 2)
        message = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("error: security onboarding worker failed", message)
        self.assertNotIn("private provider detail", message)


if __name__ == "__main__":
    unittest.main()
