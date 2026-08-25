from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every package that must stay offline and free of other bounded contexts.
ISOLATED_PACKAGES = (
    REPO_ROOT / "workers" / "quant_workspace",
    REPO_ROOT / "src" / "investment_research_os" / "quant",
    REPO_ROOT / "src" / "investment_research_os" / "quant_sources",
)

#: Top-level modules Quant is allowed to import. Everything here is either the
#: standard library or Quant's own code. Anything absent is a boundary breach,
#: which is the point: a new import has to be argued for in review rather than
#: arriving unnoticed with a feature.
ALLOWED_ROOTS = frozenset(
    {
        "__future__",
        "ast",
        "collections",
        "contextlib",
        "dataclasses",
        "datetime",
        "decimal",
        "hashlib",
        "json",
        "math",
        "os",
        "pathlib",
        "re",
        "tempfile",
        "types",
        "typing",
        "unittest",
        "uuid",
        "workers.quant_workspace",
        "investment_research_os.quant",
        "investment_research_os.quant_sources",
    }
)

#: Names that mean another bounded context, a provider, a network, or a store.
#: Checked as substrings across the whole module source, not only imports.
FORBIDDEN_TOKENS = (
    "supabase",
    "psycopg",
    "sqlite3",
    "urllib",
    "http.client",
    "httpx",
    "requests",
    "socket",
    "curl_cffi",
    "moomoo",
    "workers.portfolio",
    "workers.research",
    "workers.desktop",
    "investment_research_os.research",
    "investment_research_os.evidence",
    "yfinance",
)


def module_paths() -> list[Path]:
    paths: list[Path] = []
    for package in ISOLATED_PACKAGES:
        paths.extend(sorted(package.rglob("*.py")))
    return paths


def imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # A relative import stays inside the package it is written in.
                continue
            roots.add(node.module or "")
    return roots


def executable_source(path: Path) -> str:
    """Module source with every docstring removed.

    Prose deliberately names the boundaries Quant refuses to cross, so a raw
    text scan would flag the very sentences that document the rule. Stripping
    docstrings leaves only what actually runs.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(ast.fix_missing_locations(tree)).lower()


def is_allowed(name: str) -> bool:
    return any(
        name == allowed or name.startswith(f"{allowed}.") for allowed in ALLOWED_ROOTS
    )


class QuantIsolationTests(unittest.TestCase):
    def test_every_quant_module_is_scanned(self) -> None:
        paths = module_paths()
        self.assertGreaterEqual(len(paths), 12)
        for package in ISOLATED_PACKAGES:
            self.assertTrue(package.is_dir(), f"{package} is missing")

    def test_quant_imports_only_the_standard_library_and_its_own_code(self) -> None:
        for path in module_paths():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for name in imported_roots(tree):
                with self.subTest(module=path.name, imported=name):
                    self.assertTrue(
                        is_allowed(name),
                        f"{path.relative_to(REPO_ROOT)} imports {name!r}, which is "
                        "outside the Quant boundary",
                    )

    def test_quant_never_names_another_context_a_provider_or_a_network(self) -> None:
        for path in module_paths():
            code = executable_source(path)
            for token in FORBIDDEN_TOKENS:
                with self.subTest(module=path.name, token=token):
                    self.assertNotIn(token, code)

    def test_quant_reaches_no_clock_random_or_environment(self) -> None:
        """Determinism, stated as a rule rather than hoped for.

        A clock, a random source, or an environment lookup would make a result
        hash depend on something outside the declared inputs, and the whole
        point of the content hash is that it does not.
        """

        for path in module_paths():
            code = executable_source(path)
            for token in ("random", "time.time", "datetime.now", "os.environ", "getenv"):
                with self.subTest(module=path.name, token=token):
                    self.assertNotIn(token, code)


if __name__ == "__main__":
    unittest.main()
