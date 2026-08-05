from __future__ import annotations

import ast
from pathlib import Path
import unittest


PRODUCTION_FILES = (
    Path("workers/primary_sources/models.py"),
    Path("workers/primary_sources/adapters.py"),
    Path("workers/primary_sources/captures.py"),
    Path("workers/primary_sources/companyfacts.py"),
    Path("workers/primary_sources/corporate_actions.py"),
    Path("workers/primary_sources/eligibility.py"),
    Path("workers/primary_sources/financing.py"),
    Path("workers/primary_sources/pipeline.py"),
    Path("workers/primary_sources/plans.py"),
    Path("workers/primary_sources/temporal.py"),
    Path("workers/sec/documents.py"),
    Path("workers/sec/exhibits.py"),
    Path("workers/sec/passages.py"),
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


def predicate_mentions_ticker(predicate: ast.AST) -> bool:
    return any(
        (
            isinstance(node, ast.Name)
            and "ticker" in node.id.lower()
        )
        or (
            isinstance(node, ast.Attribute)
            and "ticker" in node.attr.lower()
        )
        for node in ast.walk(predicate)
    )


class PrimarySourceGenericGuardTests(unittest.TestCase):
    def test_primary_source_slice_has_no_ticker_or_fixture_branch(self) -> None:
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
                                for term in FORBIDDEN_FIXTURE_TERMS
                            ),
                            f"fixture-specific term found in {path}",
                        )
                    predicates: tuple[ast.AST, ...] = ()
                    if isinstance(node, (ast.If, ast.IfExp, ast.While)):
                        predicates = (node.test,)
                    elif isinstance(node, ast.Match):
                        predicates = (node.subject,)
                    elif isinstance(node, ast.comprehension):
                        predicates = tuple(node.ifs)
                    self.assertFalse(
                        any(
                            predicate_mentions_ticker(predicate)
                            for predicate in predicates
                        ),
                        f"ticker branch found in {path}",
                    )


if __name__ == "__main__":
    unittest.main()
