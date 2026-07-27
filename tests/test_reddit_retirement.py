from __future__ import annotations

import unittest
from pathlib import Path

import investment_research_os


class RedditRetirementTests(unittest.TestCase):
    def test_package_exposes_no_reddit_runtime(self) -> None:
        retired_exports = (
            "RedditApiError",
            "RedditClient",
            "RedditPost",
            "RedditSettings",
        )

        for export in retired_exports:
            with self.subTest(export=export):
                self.assertFalse(hasattr(investment_research_os, export))

    def test_repository_contains_no_callable_reddit_tracer_or_credentials(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        source_root = repository_root / "src/investment_research_os"
        project_metadata = (repository_root / "pyproject.toml").read_text()
        environment_template = (repository_root / ".env.example").read_text()
        production_source = "\n".join(
            path.read_text()
            for path in sorted(source_root.rglob("*.py"))
        )

        self.assertNotIn("investment_research_os.cli", project_metadata)
        self.assertNotIn("REDDIT_", environment_template)
        self.assertNotIn("oauth.reddit.com", production_source)
        self.assertNotIn("RedditClient", production_source)
        self.assertNotIn("RedditSettings", production_source)


if __name__ == "__main__":
    unittest.main()
