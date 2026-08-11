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


_IROS_NAME = re.compile(r"iros_[a-z0-9_]+")
_CREATE_TABLE = re.compile(
    r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?public\."
    r"(?P<table>iros_[a-z0-9_]+)\s*\(",
    re.IGNORECASE,
)
_ALTER_TABLE = re.compile(
    r"\balter\s+table\s+(?:if\s+exists\s+)?public\."
    r"(?P<table>iros_[a-z0-9_]+)\b(?P<body>[^;]*);",
    re.IGNORECASE | re.DOTALL,
)
_CREATE_UNIQUE_INDEX = re.compile(
    r"\bcreate\s+unique\s+index\s+(?:if\s+not\s+exists\s+)?"
    r"(?P<name>iros_[a-z0-9_]+)\s+on\s+public\."
    r"(?P<table>iros_[a-z0-9_]+)\b",
    re.IGNORECASE,
)
_DROP_INDEX = re.compile(
    r"\bdrop\s+index\s+(?:if\s+exists\s+)?(?:public\.)?"
    r"(?P<name>iros_[a-z0-9_]+)\b",
    re.IGNORECASE,
)
_CREATE_TRIGGER = re.compile(
    r"\bcreate\s+(?:or\s+replace\s+)?trigger\s+"
    r"(?P<name>iros_[a-z0-9_]+)\b(?P<body>[^;]*?)"
    r"\bon\s+public\.(?P<table>iros_[a-z0-9_]+)\b(?P<tail>[^;]*);",
    re.IGNORECASE | re.DOTALL,
)
_DROP_TRIGGER = re.compile(
    r"\bdrop\s+trigger\s+(?:if\s+exists\s+)?"
    r"(?P<name>iros_[a-z0-9_]+)\s+on\s+public\."
    r"(?P<table>iros_[a-z0-9_]+)\b",
    re.IGNORECASE,
)
_NAMED_CONSTRAINT = re.compile(
    r"\bconstraint\s+(?P<name>iros_[a-z0-9_]+)\s+"
    r"(?P<kind>unique|check)\b",
    re.IGNORECASE,
)
_GUARD_WORD = re.compile(
    r"(?:immutable|guard|reject|prevent|require_(?:draft|pending))",
    re.IGNORECASE,
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


def _parenthesized_body(sql: str, start: int) -> str:
    depth = 1
    index = start
    while index < len(sql):
        character = sql[index]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return sql[start:index]
        index += 1
    raise ValueError("IROS constraint table declaration is unterminated")


@dataclass(frozen=True, slots=True)
class IrosConstraintIndexEntry:
    table_name: str
    trigger_names: tuple[str, ...]
    guard_trigger_names: tuple[str, ...]
    unique_constraint_names: tuple[str, ...]
    unique_index_names: tuple[str, ...]
    check_constraint_names: tuple[str, ...]
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        table_name: str,
        trigger_names: tuple[str, ...],
        guard_trigger_names: tuple[str, ...],
        unique_constraint_names: tuple[str, ...],
        unique_index_names: tuple[str, ...],
        check_constraint_names: tuple[str, ...],
    ) -> IrosConstraintIndexEntry:
        content: dict[str, object] = {"table_name": table_name}
        for key, values in (
            ("trigger_names", trigger_names),
            ("guard_trigger_names", guard_trigger_names),
            ("unique_constraint_names", unique_constraint_names),
            ("unique_index_names", unique_index_names),
            ("check_constraint_names", check_constraint_names),
        ):
            ordered = tuple(sorted(set(values)))
            if any(_IROS_NAME.fullmatch(value) is None for value in ordered):
                raise ValueError("IROS constraint index name is invalid")
            content[key] = list(ordered)
        if _IROS_NAME.fullmatch(table_name) is None or not set(
            content["guard_trigger_names"]
        ) <= set(content["trigger_names"]):
            raise ValueError("IROS constraint index entry is invalid")
        return cls(
            table_name=table_name,
            trigger_names=tuple(content["trigger_names"]),
            guard_trigger_names=tuple(content["guard_trigger_names"]),
            unique_constraint_names=tuple(content["unique_constraint_names"]),
            unique_index_names=tuple(content["unique_index_names"]),
            check_constraint_names=tuple(content["check_constraint_names"]),
            content_sha256=_sha256(content),
        )

    @property
    def unique_enforcer_names(self) -> tuple[str, ...]:
        return tuple(sorted((*self.unique_constraint_names, *self.unique_index_names)))

    def has_valid_content_hash(self) -> bool:
        try:
            rebuilt = IrosConstraintIndexEntry.freeze(
                table_name=self.table_name,
                trigger_names=self.trigger_names,
                guard_trigger_names=self.guard_trigger_names,
                unique_constraint_names=self.unique_constraint_names,
                unique_index_names=self.unique_index_names,
                check_constraint_names=self.check_constraint_names,
            )
        except ValueError:
            return False
        return self == rebuilt


@dataclass(frozen=True, slots=True)
class IrosConstraintIndex:
    index_version: str
    migration_manifest_sha256: str
    entries: tuple[IrosConstraintIndexEntry, ...]
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        migration_manifest_sha256: str,
        entries: tuple[IrosConstraintIndexEntry, ...],
    ) -> IrosConstraintIndex:
        ordered = tuple(sorted(entries, key=lambda entry: entry.table_name))
        if (
            re.fullmatch(r"[0-9a-f]{64}", migration_manifest_sha256) is None
            or not ordered
            or len({entry.table_name for entry in ordered}) != len(ordered)
            or any(not entry.has_valid_content_hash() for entry in ordered)
        ):
            raise ValueError("IROS constraint index is invalid")
        content = {
            "index_version": "iros-constraint-index.v1",
            "migration_manifest_sha256": migration_manifest_sha256,
            "entries": [entry.content_sha256 for entry in ordered],
        }
        return cls(
            index_version="iros-constraint-index.v1",
            migration_manifest_sha256=migration_manifest_sha256,
            entries=ordered,
            content_sha256=_sha256(content),
        )

    @property
    def entries_by_table(self) -> dict[str, IrosConstraintIndexEntry]:
        return {entry.table_name: entry for entry in self.entries}

    @property
    def guarded_table_count(self) -> int:
        return sum(bool(entry.guard_trigger_names) for entry in self.entries)

    @property
    def named_unique_enforcer_count(self) -> int:
        return sum(len(entry.unique_enforcer_names) for entry in self.entries)

    @property
    def named_unique_constraint_count(self) -> int:
        return sum(len(entry.unique_constraint_names) for entry in self.entries)

    @property
    def unique_index_count(self) -> int:
        return sum(len(entry.unique_index_names) for entry in self.entries)

    def require_table(self, table_name: str) -> IrosConstraintIndexEntry:
        try:
            return self.entries_by_table[table_name]
        except KeyError as error:
            raise ValueError("IROS constraint table is absent") from error

    def contains_name(self, table_name: str, name: str) -> bool:
        entry = self.require_table(table_name)
        return name in {
            *entry.trigger_names,
            *entry.unique_enforcer_names,
            *entry.check_constraint_names,
        }

    def require_name(self, table_name: str, name: str) -> str:
        if not self.contains_name(table_name, name):
            raise ValueError("IROS constraint name is absent")
        return name

    def has_valid_content_hash(self) -> bool:
        try:
            rebuilt = IrosConstraintIndex.freeze(
                migration_manifest_sha256=self.migration_manifest_sha256,
                entries=self.entries,
            )
        except ValueError:
            return False
        return self == rebuilt


def build_iros_constraint_index(
    *,
    migration_paths: tuple[Path, ...],
) -> IrosConstraintIndex:
    ordered_paths = tuple(sorted(migration_paths, key=lambda path: path.name))
    audit = audit_iros_migration_batch(ordered_paths)
    if not audit.passed:
        raise ValueError("IROS constraint index migration audit failed")

    tables: set[str] = set()
    triggers: dict[str, set[str]] = {}
    guard_triggers: dict[str, set[str]] = {}
    unique_constraints: dict[str, set[str]] = {}
    unique_indexes: dict[str, set[str]] = {}
    index_owners: dict[str, str] = {}
    check_constraints: dict[str, set[str]] = {}

    for path in ordered_paths:
        sql = strip_sql_comments_and_literals(path.read_text())
        for match in _CREATE_TABLE.finditer(sql):
            table = match.group("table").lower()
            tables.add(table)
            body = _parenthesized_body(sql, match.end())
            for constraint in _NAMED_CONSTRAINT.finditer(body):
                name = constraint.group("name").lower()
                destination = (
                    unique_constraints
                    if constraint.group("kind").lower() == "unique"
                    else check_constraints
                )
                destination.setdefault(table, set()).add(name)

        events: list[tuple[int, str, re.Match[str]]] = []
        for kind, pattern in (
            ("alter", _ALTER_TABLE),
            ("create_index", _CREATE_UNIQUE_INDEX),
            ("drop_index", _DROP_INDEX),
            ("create_trigger", _CREATE_TRIGGER),
            ("drop_trigger", _DROP_TRIGGER),
        ):
            events.extend(
                (match.start(), kind, match) for match in pattern.finditer(sql)
            )
        for _, event_kind, match in sorted(events, key=lambda item: item[0]):
            if event_kind == "alter":
                table = match.group("table").lower()
                body = match.group("body")
                for drop in re.finditer(
                    r"\bdrop\s+constraint\s+(?:if\s+exists\s+)?"
                    r"(iros_[a-z0-9_]+)\b",
                    body,
                    re.IGNORECASE,
                ):
                    name = drop.group(1).lower()
                    unique_constraints.setdefault(table, set()).discard(name)
                    check_constraints.setdefault(table, set()).discard(name)
                for constraint in re.finditer(
                    r"\badd\s+constraint\s+(?P<name>iros_[a-z0-9_]+)\s+"
                    r"(?P<kind>unique|check)\b",
                    body,
                    re.IGNORECASE,
                ):
                    name = constraint.group("name").lower()
                    destination = (
                        unique_constraints
                        if constraint.group("kind").lower() == "unique"
                        else check_constraints
                    )
                    destination.setdefault(table, set()).add(name)
            elif event_kind == "create_index":
                name = match.group("name").lower()
                table = match.group("table").lower()
                prior_table = index_owners.get(name)
                if prior_table is not None:
                    unique_indexes.setdefault(prior_table, set()).discard(name)
                index_owners[name] = table
                unique_indexes.setdefault(table, set()).add(name)
            elif event_kind == "drop_index":
                name = match.group("name").lower()
                table = index_owners.pop(name, None)
                if table is not None:
                    unique_indexes.setdefault(table, set()).discard(name)
            elif event_kind == "create_trigger":
                name = match.group("name").lower()
                table = match.group("table").lower()
                statement = f"{name} {match.group('body')} {match.group('tail')}"
                triggers.setdefault(table, set()).add(name)
                if _GUARD_WORD.search(statement):
                    guard_triggers.setdefault(table, set()).add(name)
            else:
                name = match.group("name").lower()
                table = match.group("table").lower()
                triggers.setdefault(table, set()).discard(name)
                guard_triggers.setdefault(table, set()).discard(name)

    entries = tuple(
        IrosConstraintIndexEntry.freeze(
            table_name=table,
            trigger_names=tuple(triggers.get(table, set())),
            guard_trigger_names=tuple(guard_triggers.get(table, set())),
            unique_constraint_names=tuple(unique_constraints.get(table, set())),
            unique_index_names=tuple(unique_indexes.get(table, set())),
            check_constraint_names=tuple(check_constraints.get(table, set())),
        )
        for table in tables
    )
    return IrosConstraintIndex.freeze(
        migration_manifest_sha256=_sha256(
            [
                {
                    "filename": entry.path.name,
                    "content_sha256": entry.content_sha256,
                }
                for entry in audit.manifest
            ]
        ),
        entries=entries,
    )


__all__ = [
    "IrosConstraintIndex",
    "IrosConstraintIndexEntry",
    "build_iros_constraint_index",
]
