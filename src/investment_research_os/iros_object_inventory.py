from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from investment_research_os.migration_audit import (
    audit_iros_migration_batch,
    strip_sql_comments_and_literals,
)


_CLIENT_ROLES = ("anon", "authenticated")
_KNOWN_ROLES = ("public", "anon", "authenticated", "service_role")
_OBJECT_KINDS = ("table", "view", "function")
_TABLE_PRIVILEGES = frozenset({"delete", "insert", "select", "update"})
_FUNCTION_PRIVILEGES = frozenset({"execute"})
_IROS_OBJECT = re.compile(r"iros_[a-z0-9_]+")
_DECLARATION = re.compile(
    r"\bcreate\s+(?:or\s+replace\s+)?(?P<kind>table|view|function)\s+"
    r"(?:if\s+not\s+exists\s+)?public\.(?P<name>iros_[a-z0-9_]+)\b",
    re.IGNORECASE,
)
_GRANT_OR_REVOKE = re.compile(
    r"\b(?P<action>grant|revoke)\b(?P<body>[^;]*);",
    re.IGNORECASE | re.DOTALL,
)
_POLICY = re.compile(
    r"\b(?P<action>create|drop)\s+policy\s+(?:if\s+exists\s+)?"
    r"(?P<policy>[a-z_][a-z0-9_]*)\s+on\s+public\."
    r"(?P<table>iros_[a-z0-9_]+)\b",
    re.IGNORECASE,
)
_TRIGGER_FUNCTION = re.compile(
    r"\bcreate\s+(?:or\s+replace\s+)?trigger\s+[a-z_][a-z0-9_]*\b"
    r"[^;]*?\bexecute\s+function\s+public\."
    r"(?P<function>iros_[a-z0-9_]+)\s*\(",
    re.IGNORECASE | re.DOTALL,
)


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def _roles(fragment: str) -> tuple[str, ...]:
    return tuple(
        role
        for role in _KNOWN_ROLES
        if re.search(rf"\b{re.escape(role)}\b", fragment, re.IGNORECASE)
    )


def _privileges(fragment: str, object_kind: str) -> frozenset[str]:
    lowered = fragment.lower()
    if re.search(r"\ball(?:\s+privileges)?\b", lowered):
        if object_kind == "function":
            return frozenset({"execute"})
        return frozenset({"select", "insert", "update", "delete"})
    allowed = (
        {"execute"}
        if object_kind == "function"
        else {
            "select",
            "insert",
            "update",
            "delete",
        }
    )
    return frozenset(
        privilege for privilege in allowed if re.search(rf"\b{privilege}\b", lowered)
    )


def _effective_client_privileges(
    grants: dict[str, set[str]],
    role: str,
) -> frozenset[str]:
    return frozenset(grants["public"] | grants[role])


@dataclass(frozen=True, slots=True)
class IrosObjectInventoryEntry:
    object_name: str
    object_kind: str
    migration_filenames: tuple[str, ...]
    exposed_roles: tuple[str, ...]
    anon_privileges: tuple[str, ...]
    authenticated_privileges: tuple[str, ...]
    service_role_privileges: tuple[str, ...]
    rls_enabled: bool | None
    rls_forced: bool | None
    policy_count: int | None
    security_invoker: bool | None
    security_definer: bool | None
    inclusion: str
    reason_code: str
    grant_history_reason_codes: tuple[str, ...]
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        object_name: str,
        object_kind: str,
        migration_filenames: tuple[str, ...],
        exposed_roles: tuple[str, ...],
        anon_privileges: tuple[str, ...],
        authenticated_privileges: tuple[str, ...],
        service_role_privileges: tuple[str, ...],
        rls_enabled: bool | None,
        rls_forced: bool | None,
        policy_count: int | None,
        security_invoker: bool | None,
        security_definer: bool | None,
        inclusion: str,
        reason_code: str,
        grant_history_reason_codes: tuple[str, ...],
    ) -> IrosObjectInventoryEntry:
        ordered_files = tuple(sorted(set(migration_filenames)))
        ordered_roles = tuple(sorted(set(exposed_roles)))
        ordered_anon_privileges = tuple(sorted(set(anon_privileges)))
        ordered_authenticated_privileges = tuple(sorted(set(authenticated_privileges)))
        ordered_service_privileges = tuple(sorted(set(service_role_privileges)))
        ordered_history = tuple(sorted(set(grant_history_reason_codes)))
        allowed_privileges = (
            _FUNCTION_PRIVILEGES if object_kind == "function" else _TABLE_PRIVILEGES
        )
        expected_roles = tuple(
            role
            for role, privileges in (
                ("anon", ordered_anon_privileges),
                ("authenticated", ordered_authenticated_privileges),
            )
            if privileges
        )
        if (
            _IROS_OBJECT.fullmatch(object_name) is None
            or object_kind not in _OBJECT_KINDS
            or not ordered_files
            or any(role not in _CLIENT_ROLES for role in ordered_roles)
            or ordered_roles != expected_roles
            or any(
                privilege not in allowed_privileges
                for privilege in (
                    *ordered_anon_privileges,
                    *ordered_authenticated_privileges,
                    *ordered_service_privileges,
                )
            )
            or inclusion not in {"included", "excluded"}
            or not reason_code
            or any(code != "explicitly_revoked" for code in ordered_history)
        ):
            raise ValueError("IROS object inventory entry is invalid")
        if object_kind == "table":
            if (
                not isinstance(rls_enabled, bool)
                or not isinstance(rls_forced, bool)
                or not isinstance(policy_count, int)
                or policy_count < 0
                or security_invoker is not None
                or security_definer is not None
            ):
                raise ValueError("IROS table inventory posture is invalid")
        elif object_kind == "view":
            if not isinstance(security_invoker, bool) or any(
                value is not None
                for value in (
                    rls_enabled,
                    rls_forced,
                    policy_count,
                    security_definer,
                )
            ):
                raise ValueError("IROS view inventory posture is invalid")
        elif not isinstance(security_definer, bool) or any(
            value is not None
            for value in (
                rls_enabled,
                rls_forced,
                policy_count,
                security_invoker,
            )
        ):
            raise ValueError("IROS function inventory posture is invalid")
        content = {
            "object_name": object_name,
            "object_kind": object_kind,
            "migration_filenames": list(ordered_files),
            "exposed_roles": list(ordered_roles),
            "anon_privileges": list(ordered_anon_privileges),
            "authenticated_privileges": list(ordered_authenticated_privileges),
            "service_role_privileges": list(ordered_service_privileges),
            "rls_enabled": rls_enabled,
            "rls_forced": rls_forced,
            "policy_count": policy_count,
            "security_invoker": security_invoker,
            "security_definer": security_definer,
            "inclusion": inclusion,
            "reason_code": reason_code,
            "grant_history_reason_codes": list(ordered_history),
        }
        return cls(
            object_name=object_name,
            object_kind=object_kind,
            migration_filenames=ordered_files,
            exposed_roles=ordered_roles,
            anon_privileges=ordered_anon_privileges,
            authenticated_privileges=ordered_authenticated_privileges,
            service_role_privileges=ordered_service_privileges,
            rls_enabled=rls_enabled,
            rls_forced=rls_forced,
            policy_count=policy_count,
            security_invoker=security_invoker,
            security_definer=security_definer,
            inclusion=inclusion,
            reason_code=reason_code,
            grant_history_reason_codes=ordered_history,
            content_sha256=_sha256(content),
        )

    def has_valid_content_hash(self) -> bool:
        try:
            rebuilt = IrosObjectInventoryEntry.freeze(
                object_name=self.object_name,
                object_kind=self.object_kind,
                migration_filenames=self.migration_filenames,
                exposed_roles=self.exposed_roles,
                anon_privileges=self.anon_privileges,
                authenticated_privileges=self.authenticated_privileges,
                service_role_privileges=self.service_role_privileges,
                rls_enabled=self.rls_enabled,
                rls_forced=self.rls_forced,
                policy_count=self.policy_count,
                security_invoker=self.security_invoker,
                security_definer=self.security_definer,
                inclusion=self.inclusion,
                reason_code=self.reason_code,
                grant_history_reason_codes=self.grant_history_reason_codes,
            )
        except ValueError:
            return False
        return self == rebuilt


@dataclass(frozen=True, slots=True)
class IrosObjectInventory:
    inventory_version: str
    migration_manifest_sha256: str
    entries: tuple[IrosObjectInventoryEntry, ...]
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        migration_manifest_sha256: str,
        entries: tuple[IrosObjectInventoryEntry, ...],
    ) -> IrosObjectInventory:
        ordered = tuple(sorted(entries, key=lambda item: item.object_name))
        if (
            re.fullmatch(r"[0-9a-f]{64}", migration_manifest_sha256) is None
            or not ordered
            or len({entry.object_name for entry in ordered}) != len(ordered)
            or any(not entry.has_valid_content_hash() for entry in ordered)
        ):
            raise ValueError("IROS object inventory is invalid")
        content = {
            "inventory_version": "iros-object-inventory.v1",
            "migration_manifest_sha256": migration_manifest_sha256,
            "entries": [entry.content_sha256 for entry in ordered],
        }
        return cls(
            inventory_version="iros-object-inventory.v1",
            migration_manifest_sha256=migration_manifest_sha256,
            entries=ordered,
            content_sha256=_sha256(content),
        )

    @property
    def entries_by_name(self) -> dict[str, IrosObjectInventoryEntry]:
        return {entry.object_name: entry for entry in self.entries}

    @property
    def declared_count(self) -> int:
        return len(self.entries)

    @property
    def kind_counts(self) -> dict[str, int]:
        return {
            kind: sum(entry.object_kind == kind for entry in self.entries)
            for kind in _OBJECT_KINDS
        }

    @property
    def client_exposed_count(self) -> int:
        return sum(bool(entry.exposed_roles) for entry in self.entries)

    @property
    def client_exposed_role_counts(self) -> dict[str, int]:
        return {
            role: sum(role in entry.exposed_roles for entry in self.entries)
            for role in _CLIENT_ROLES
        }

    @property
    def deny_all_probe_count(self) -> int:
        return sum(
            entry.reason_code == "deny_all_probe_required" for entry in self.entries
        )

    @property
    def rls_enabled_table_count(self) -> int:
        return sum(entry.rls_enabled is True for entry in self.entries)

    @property
    def rls_forced_table_count(self) -> int:
        return sum(entry.rls_forced is True for entry in self.entries)

    @property
    def security_invoker_view_count(self) -> int:
        return sum(entry.security_invoker is True for entry in self.entries)

    def has_valid_content_hash(self) -> bool:
        try:
            rebuilt = IrosObjectInventory.freeze(
                migration_manifest_sha256=self.migration_manifest_sha256,
                entries=self.entries,
            )
        except ValueError:
            return False
        return self == rebuilt


def _declaration_headers(
    sql: str,
    matches: tuple[re.Match[str], ...],
) -> dict[str, str]:
    headers: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(sql)
        headers[match.group("name").lower()] = sql[match.start() : end]
    return headers


def build_iros_object_inventory(
    *,
    migration_paths: tuple[Path, ...],
) -> IrosObjectInventory:
    ordered_paths = tuple(sorted(migration_paths, key=lambda path: path.name))
    audit = audit_iros_migration_batch(ordered_paths)
    if not audit.passed:
        raise ValueError("IROS object inventory migration audit failed")

    kinds: dict[str, str] = {}
    filenames: dict[str, set[str]] = {}
    grants: dict[str, dict[str, set[str]]] = {}
    explicit_revocations: set[str] = set()
    rls_enabled: set[str] = set()
    rls_forced: set[str] = set()
    policies: dict[str, set[str]] = {}
    security_invoker: dict[str, bool] = {}
    security_definer: dict[str, bool] = {}
    trigger_functions: set[str] = set()

    sanitized_by_path: dict[Path, str] = {}
    for path in ordered_paths:
        sql = strip_sql_comments_and_literals(path.read_text())
        sanitized_by_path[path] = sql
        matches = tuple(_DECLARATION.finditer(sql))
        headers = _declaration_headers(sql, matches)
        for match in matches:
            name = match.group("name").lower()
            kind = match.group("kind").lower()
            prior_kind = kinds.get(name)
            if prior_kind is not None and prior_kind != kind:
                raise ValueError("IROS object kind changed across migrations")
            first_declaration = name not in kinds
            kinds[name] = kind
            filenames.setdefault(name, set()).add(path.name)
            object_grants = grants.setdefault(
                name,
                {role: set() for role in _KNOWN_ROLES},
            )
            if first_declaration and kind == "function":
                object_grants["public"].add("execute")
            header = headers[name]
            if kind == "view":
                security_invoker[name] = bool(
                    re.search(
                        r"\bsecurity_invoker\s*=\s*true\b",
                        header,
                        re.IGNORECASE,
                    )
                )
            elif kind == "function":
                security_definer[name] = bool(
                    re.search(r"\bsecurity\s+definer\b", header, re.IGNORECASE)
                )

        for match in re.finditer(
            r"\balter\s+table\s+public\.(iros_[a-z0-9_]+)\s+"
            r"(?P<force>force\s+row\s+level\s+security|"
            r"no\s+force\s+row\s+level\s+security|"
            r"enable\s+row\s+level\s+security|"
            r"disable\s+row\s+level\s+security)\b",
            sql,
            re.IGNORECASE,
        ):
            table = match.group(1).lower()
            action = " ".join(match.group("force").lower().split())
            if action == "enable row level security":
                rls_enabled.add(table)
            elif action == "disable row level security":
                rls_enabled.discard(table)
            elif action == "force row level security":
                rls_forced.add(table)
            else:
                rls_forced.discard(table)

        for match in _POLICY.finditer(sql):
            table = match.group("table").lower()
            policy = match.group("policy").lower()
            table_policies = policies.setdefault(table, set())
            if match.group("action").lower() == "create":
                table_policies.add(policy)
            else:
                table_policies.discard(policy)
        trigger_functions.update(
            match.group("function").lower() for match in _TRIGGER_FUNCTION.finditer(sql)
        )

        for match in _GRANT_OR_REVOKE.finditer(sql):
            action = match.group("action").lower()
            body = match.group("body")
            object_match = re.search(
                r"\bon\s+(?P<kind>table|function)\s+(?P<objects>.*?)\s+"
                r"(?P<direction>to|from)\s+(?P<roles>.*)\Z",
                body,
                re.IGNORECASE | re.DOTALL,
            )
            if object_match is None:
                continue
            statement_kind = object_match.group("kind").lower()
            role_names = _roles(object_match.group("roles"))
            for name_match in re.finditer(
                r"\bpublic\.(iros_[a-z0-9_]+)\b",
                object_match.group("objects"),
                re.IGNORECASE,
            ):
                name = name_match.group(1).lower()
                if name not in grants:
                    continue
                privileges = _privileges(
                    body[: object_match.start()],
                    "function" if statement_kind == "function" else "table",
                )
                if action == "revoke":
                    for role in role_names:
                        grants[name][role].difference_update(privileges)
                    if privileges and any(
                        role in {"public", *_CLIENT_ROLES} for role in role_names
                    ):
                        explicit_revocations.add(name)
                else:
                    for role in role_names:
                        grants[name][role].update(privileges)

    entries: list[IrosObjectInventoryEntry] = []
    for name, kind in kinds.items():
        exposed_roles = tuple(
            role
            for role in _CLIENT_ROLES
            if _effective_client_privileges(grants[name], role)
        )
        anon_privileges = tuple(
            sorted(_effective_client_privileges(grants[name], "anon"))
        )
        authenticated_privileges = tuple(
            sorted(_effective_client_privileges(grants[name], "authenticated"))
        )
        service_privileges = tuple(sorted(grants[name]["service_role"]))
        table_rls = name in rls_enabled if kind == "table" else None
        table_forced = name in rls_forced if kind == "table" else None
        policy_count = len(policies.get(name, set())) if kind == "table" else None
        view_invoker = security_invoker.get(name, False) if kind == "view" else None
        function_definer = (
            security_definer.get(name, False) if kind == "function" else None
        )
        deny_all = (
            kind == "table"
            and table_rls is True
            and policy_count == 0
            and not exposed_roles
        )
        if exposed_roles:
            inclusion = "included"
            reason_code = f"client_exposed_{kind}"
        elif deny_all:
            inclusion = "included"
            reason_code = "deny_all_probe_required"
        else:
            inclusion = "excluded"
            if service_privileges:
                reason_code = "service_role_only"
            elif kind == "function" and name in trigger_functions:
                reason_code = "trigger_function_only"
            elif kind == "function":
                reason_code = "internal_helper_function"
            else:
                reason_code = "not_client_exposed"
        entries.append(
            IrosObjectInventoryEntry.freeze(
                object_name=name,
                object_kind=kind,
                migration_filenames=tuple(filenames[name]),
                exposed_roles=exposed_roles,
                anon_privileges=anon_privileges,
                authenticated_privileges=authenticated_privileges,
                service_role_privileges=service_privileges,
                rls_enabled=table_rls,
                rls_forced=table_forced,
                policy_count=policy_count,
                security_invoker=view_invoker,
                security_definer=function_definer,
                inclusion=inclusion,
                reason_code=reason_code,
                grant_history_reason_codes=(
                    ("explicitly_revoked",) if name in explicit_revocations else ()
                ),
            )
        )
    return IrosObjectInventory.freeze(
        migration_manifest_sha256=_sha256(
            [
                {
                    "filename": entry.path.name,
                    "content_sha256": entry.content_sha256,
                }
                for entry in audit.manifest
            ]
        ),
        entries=tuple(entries),
    )


__all__ = [
    "IrosObjectInventory",
    "IrosObjectInventoryEntry",
    "build_iros_object_inventory",
]
