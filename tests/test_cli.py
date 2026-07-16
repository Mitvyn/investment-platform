from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from investment_research_os.cli import run


class CliTests(unittest.TestCase):
    def test_api_access_is_disabled_without_explicit_approval(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.stderr") as stderr:
                exit_code = run(["fetch-new", "--subreddit", "stocks"])

        self.assertEqual(exit_code, 2)
        message = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("explicit approval", message)
        self.assertNotIn("client_secret=", message)

    def test_missing_credentials_returns_error_after_approval(self) -> None:
        with patch.dict(os.environ, {"REDDIT_API_APPROVED": "true"}, clear=True):
            with patch("sys.stderr") as stderr:
                exit_code = run(["fetch-new", "--subreddit", "stocks"])

        self.assertEqual(exit_code, 2)
        message = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("REDDIT_CLIENT_ID", message)
        self.assertNotIn("client_secret=", message)


if __name__ == "__main__":
    unittest.main()
