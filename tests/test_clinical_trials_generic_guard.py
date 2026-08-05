from __future__ import annotations

import ast
from pathlib import Path
import unittest


PRODUCTION_FILES = tuple(
    sorted(Path("workers/clinical_trials").glob("*.py"))
)
FORBIDDEN_SECURITY_TERMS = (
    "ticker",
    "rxrx",
    "recursion",
    "single asset",
    "fixture",
)


class ClinicalTrialsGenericGuardTests(unittest.TestCase):
    def test_adapter_has_no_security_specific_branch_or_fixture_override(
        self,
    ) -> None:
        self.assertTrue(PRODUCTION_FILES)
        for path in PRODUCTION_FILES:
            source = path.read_text()
            tree = ast.parse(source, filename=str(path))
            with self.subTest(path=path):
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and isinstance(
                        node.value,
                        str,
                    ):
                        normalized = node.value.lower()
                        self.assertFalse(
                            any(
                                term in normalized
                                for term in FORBIDDEN_SECURITY_TERMS
                            ),
                            f"security-specific term found in {path}",
                        )


if __name__ == "__main__":
    unittest.main()
