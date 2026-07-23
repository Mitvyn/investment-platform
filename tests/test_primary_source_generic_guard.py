from __future__ import annotations

import ast
from pathlib import Path
import unittest


PRODUCTION_FILES = (
    Path("workers/primary_sources/models.py"),
    Path("workers/primary_sources/temporal.py"),
    Path("workers/sec/selection.py"),
    Path("workers/sec/submissions.py"),
)
FORBIDDEN_FIXTURE_TERMS = (
    "rxrx",
    "recursion",
    "satx",
    "single asset",
    "sabx",
)


class PrimarySourceGenericGuardTests(unittest.TestCase):
    def test_primary_source_slice_has_no_ticker_or_fixture_branch(self) -> None:
        for path in PRODUCTION_FILES:
            source = path.read_text()
            tree = ast.parse(source, filename=str(path))
            with self.subTest(path=path):
                self.assertNotIn("ticker", source.lower())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and isinstance(
                        node.value,
                        str,
                    ):
                        normalized = node.value.lower()
                        self.assertFalse(
                            any(
                                term in normalized
                                for term in FORBIDDEN_FIXTURE_TERMS
                            ),
                            f"fixture-specific term found in {path}",
                        )


if __name__ == "__main__":
    unittest.main()
