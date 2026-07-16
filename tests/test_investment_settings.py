from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from investment_research_os.config import ConfigError, RedditSettings


class InvestmentSettingsTests(unittest.TestCase):
    def test_accepts_official_user_agent_shape(self) -> None:
        with patch.dict(
            os.environ,
            {
                "REDDIT_API_APPROVED": "true",
                "REDDIT_CLIENT_ID": "client-id",
                "REDDIT_CLIENT_SECRET": "client-secret",
                "REDDIT_USER_AGENT": (
                    "macos:investment-research-os:v0.1.0 (by /u/example_user)"
                ),
            },
            clear=True,
        ):
            settings = RedditSettings.from_env()

        self.assertEqual(
            settings.user_agent,
            "macos:investment-research-os:v0.1.0 (by /u/example_user)",
        )

    def test_rejects_placeholder_user_agent(self) -> None:
        with patch.dict(
            os.environ,
            {
                "REDDIT_API_APPROVED": "true",
                "REDDIT_CLIENT_ID": "client-id",
                "REDDIT_CLIENT_SECRET": "client-secret",
                "REDDIT_USER_AGENT": (
                    "macos:investment-research-os:v0.1.0 (by /u/your_reddit_username)"
                ),
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ConfigError, "must match"):
                RedditSettings.from_env()


if __name__ == "__main__":
    unittest.main()
