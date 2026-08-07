from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Iterable


@dataclass(frozen=True)
class MigrationManifestEntry:
    path: Path
    content_sha256: str


@dataclass(frozen=True)
class MigrationAuditViolation:
    path: Path
    rule_id: str
    detail: str


@dataclass(frozen=True)
class MigrationAuditReport:
    manifest: tuple[MigrationManifestEntry, ...]
    violations: tuple[MigrationAuditViolation, ...]

    @property
    def passed(self) -> bool:
        return not self.violations

    @property
    def batch_sha256(self) -> str:
        canonical_manifest = "".join(
            f"{entry.path.name}:{entry.content_sha256}\n"
            for entry in self.manifest
        ).encode()
        return hashlib.sha256(canonical_manifest).hexdigest()


def audit_iros_migration_batch(paths: Iterable[Path]) -> MigrationAuditReport:
    ordered_paths = tuple(
        sorted((Path(path) for path in paths), key=lambda path: path.name)
    )
    manifest = tuple(
        MigrationManifestEntry(
            path=path,
            content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in ordered_paths
    )
    violations: list[MigrationAuditViolation] = []
    if not ordered_paths:
        violations.append(
            MigrationAuditViolation(
                path=Path("<batch>"),
                rule_id="batch.empty",
                detail="migration review batch must not be empty",
            )
        )
    seen_paths: set[Path] = set()
    for path in ordered_paths:
        resolved_path = path.resolve()
        if resolved_path in seen_paths:
            violations.append(
                MigrationAuditViolation(
                    path=path,
                    rule_id="batch.duplicate_path",
                    detail=f"{path.name} appears more than once",
                )
            )
        seen_paths.add(resolved_path)
    for path in ordered_paths:
        sql = strip_sql_comments_and_literals(path.read_text())
        findings: list[tuple[int, MigrationAuditViolation]] = []
        for match in re.finditer(r"\bpublic\.([a-z_][a-z0-9_]*)\b", sql, re.I):
            object_name = match.group(1).lower()
            if not object_name.startswith("iros_"):
                findings.append(
                    (
                        match.start(),
                        MigrationAuditViolation(
                            path=path,
                            rule_id="namespace.public_object_prefix",
                            detail=(
                                f"public.{object_name} is outside iros_ namespace"
                            ),
                        ),
                    )
                )
        for match in re.finditer(
            r"\breferences\s+([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b",
            sql,
            re.I,
        ):
            schema_name = match.group(1).lower()
            object_name = match.group(2).lower()
            if not (
                (schema_name == "public" and object_name.startswith("iros_"))
                or (schema_name == "auth" and object_name == "users")
            ):
                findings.append(
                    (
                        match.start(),
                        MigrationAuditViolation(
                            path=path,
                            rule_id="namespace.cross_project_schema",
                            detail=(
                                f"foreign key target {schema_name}.{object_name} "
                                "is outside approved IROS ownership"
                            ),
                        ),
                    )
                )
        for pattern, rule_id, detail in (
            (
                r"\b(?:grant|revoke)\b[^;]*\bon\s+schema\b",
                "grants.schema_wide",
                "schema-wide grant or revoke is forbidden",
            ),
            (
                r"\balter\s+default\s+privileges\b",
                "grants.default_privileges",
                "default privilege changes are forbidden",
            ),
            (
                r"\bon\s+all\s+(?:tables|sequences|functions)\b",
                "grants.schema_wide",
                "all-object grants or revokes are forbidden",
            ),
        ):
            for match in re.finditer(pattern, sql, re.I | re.S):
                findings.append(
                    (
                        match.start(),
                        MigrationAuditViolation(
                            path=path,
                            rule_id=rule_id,
                            detail=detail,
                        ),
                    )
                )
        for match in re.finditer(
            r"\bcreate\s+table\s+public\.(iros_[a-z0-9_]+)\b",
            sql,
            re.I,
        ):
            table_name = match.group(1).lower()
            rls_pattern = (
                rf"\balter\s+table\s+public\.{re.escape(table_name)}\s+"
                r"enable\s+row\s+level\s+security\b"
            )
            if not re.search(rls_pattern, sql, re.I):
                findings.append(
                    (
                        match.start(),
                        MigrationAuditViolation(
                            path=path,
                            rule_id="rls.created_table_missing",
                            detail=f"public.{table_name} does not enable RLS",
                        ),
                    )
                )
            if not _has_explicit_anon_authenticated_revoke(sql, table_name):
                findings.append(
                    (
                        match.start(),
                        MigrationAuditViolation(
                            path=path,
                            rule_id="grants.explicit_revoke_missing",
                            detail=(
                                f"public.{table_name} lacks explicit anon and "
                                "authenticated revoke"
                            ),
                        ),
                    )
                )
        for match in re.finditer(
            r"\bcreate\s+(?:or\s+replace\s+)?view\s+"
            r"public\.(iros_[a-z0-9_]+)\b",
            sql,
            re.I,
        ):
            view_name = match.group(1).lower()
            view_tail = sql[match.end() :]
            statement_end = view_tail.find(";")
            statement = view_tail if statement_end < 0 else view_tail[:statement_end]
            if not re.search(
                r"\bwith\s*\(\s*security_invoker\s*=\s*true\s*\)",
                statement,
                re.I,
            ):
                findings.append(
                    (
                        match.start(),
                        MigrationAuditViolation(
                            path=path,
                            rule_id="views.security_invoker_missing",
                            detail=f"public.{view_name} is not security invoker",
                        ),
                    )
                )
            if not _has_explicit_anon_authenticated_revoke(sql, view_name):
                findings.append(
                    (
                        match.start(),
                        MigrationAuditViolation(
                            path=path,
                            rule_id="grants.explicit_revoke_missing",
                            detail=(
                                f"public.{view_name} lacks explicit anon and "
                                "authenticated revoke"
                            ),
                        ),
                    )
                )
        for match in re.finditer(
            r"\bcreate\s+(?:or\s+replace\s+)?function\s+"
            r"public\.(iros_[a-z0-9_]+)\s*\([^)]*\)"
            r"(?P<header>.*?)\bas\s+\$[a-z0-9_]*\$",
            sql,
            re.I | re.S,
        ):
            header = match.group("header")
            if not re.search(r"\bsecurity\s+definer\b", header, re.I):
                continue
            function_name = match.group(1).lower()
            if not re.search(
                r"\bset\s+search_path\s*=\s*''",
                header,
                re.I,
            ):
                findings.append(
                    (
                        match.start(),
                        MigrationAuditViolation(
                            path=path,
                            rule_id="functions.security_definer_search_path",
                            detail=(
                                f"public.{function_name} must set empty search_path"
                            ),
                        ),
                    )
                )
            if not _has_explicit_function_execute_revoke(sql, function_name):
                findings.append(
                    (
                        match.start(),
                        MigrationAuditViolation(
                            path=path,
                            rule_id="functions.execute_revoke_missing",
                            detail=(
                                f"public.{function_name} lacks PUBLIC and anon "
                                "execute revoke"
                            ),
                        ),
                    )
                )
        violations.extend(
            violation
            for _, violation in sorted(findings, key=lambda item: item[0])
        )
    return MigrationAuditReport(
        manifest=manifest,
        violations=tuple(violations),
    )


def strip_sql_comments_and_literals(sql: str) -> str:
    without_block_comments = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    without_line_comments = re.sub(r"--[^\n]*", " ", without_block_comments)
    return re.sub(r"'(?:''|[^'])*'", "''", without_line_comments)


def _has_explicit_anon_authenticated_revoke(sql: str, object_name: str) -> bool:
    object_ref = f"public.{object_name}".lower()
    for match in re.finditer(r"\brevoke\b[^;]*;", sql, re.I | re.S):
        statement = " ".join(match.group(0).lower().split())
        if not re.search(rf"\b{re.escape(object_ref)}\b", statement) or (
            " on table " not in statement
        ):
            continue
        _, separator, roles = statement.partition(" from ")
        if separator and re.search(r"\banon\b", roles) and re.search(
            r"\bauthenticated\b", roles
        ):
            return True
    return False


def _has_explicit_function_execute_revoke(sql: str, function_name: str) -> bool:
    object_ref = f"public.{function_name}".lower()
    for match in re.finditer(r"\brevoke\b[^;]*;", sql, re.I | re.S):
        statement = " ".join(match.group(0).lower().split())
        if not re.search(rf"\b{re.escape(object_ref)}\b", statement) or (
            " on function " not in statement
        ):
            continue
        _, separator, roles = statement.partition(" from ")
        if separator and re.search(r"\bpublic\b", roles) and re.search(
            r"\banon\b", roles
        ):
            return True
    return False


__all__ = [
    "MigrationAuditReport",
    "MigrationAuditViolation",
    "MigrationManifestEntry",
    "audit_iros_migration_batch",
    "strip_sql_comments_and_literals",
]
