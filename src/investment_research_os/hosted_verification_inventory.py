from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from investment_research_os.migration_audit import (
    audit_iros_migration_batch,
    strip_sql_comments_and_literals,
)


_IROS_OBJECT = re.compile(r"iros_[a-z0-9_]+")
_MIGRATION_FILENAME = re.compile(r"[0-9]{14}_iros_[a-z0-9_]+\.sql")
_DECLARATION = re.compile(
    r"\bcreate\s+(?:or\s+replace\s+)?(?P<kind>table|view|function)\s+"
    r"(?:if\s+not\s+exists\s+)?public\.(?P<name>iros_[a-z0-9_]+)\b",
    re.IGNORECASE,
)
_EXCLUSION_REASONS = frozenset(
    {
        "derived_read_model_not_directly_probed",
        "integrity_function_not_directly_probed",
        "private_persistence_not_directly_probed",
        "runtime_rpc_not_directly_probed",
        "superseded_object_not_directly_probed",
    }
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


@dataclass(frozen=True, slots=True)
class HostedMigrationObjectDisposition:
    object_name: str
    object_kind: str
    migration_filenames: tuple[str, ...]
    disposition: str
    reason_code: str
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        object_name: str,
        object_kind: str,
        migration_filenames: tuple[str, ...],
        disposition: str,
        reason_code: str,
    ) -> HostedMigrationObjectDisposition:
        if _IROS_OBJECT.fullmatch(object_name) is None:
            raise ValueError("hosted verification inventory object is invalid")
        if object_kind not in {"table", "view", "function"}:
            raise ValueError("hosted verification inventory object kind is invalid")
        ordered_filenames = tuple(sorted(migration_filenames))
        if (
            not ordered_filenames
            or len(set(ordered_filenames)) != len(ordered_filenames)
            or any(
                _MIGRATION_FILENAME.fullmatch(filename) is None
                for filename in ordered_filenames
            )
        ):
            raise ValueError("hosted verification inventory migrations are invalid")
        if disposition == "execution_target":
            if reason_code != "required_by_execution_dispatch":
                raise ValueError("hosted verification inventory reason is invalid")
        elif disposition == "excluded":
            if reason_code not in _EXCLUSION_REASONS:
                raise ValueError("hosted verification inventory reason is invalid")
        else:
            raise ValueError("hosted verification inventory disposition is invalid")
        content = {
            "object_name": object_name,
            "object_kind": object_kind,
            "migration_filenames": list(ordered_filenames),
            "disposition": disposition,
            "reason_code": reason_code,
        }
        return cls(
            object_name=object_name,
            object_kind=object_kind,
            migration_filenames=ordered_filenames,
            disposition=disposition,
            reason_code=reason_code,
            content_sha256=_sha256(content),
        )

    def has_valid_content_hash(self) -> bool:
        if (
            _IROS_OBJECT.fullmatch(self.object_name) is None
            or self.object_kind not in {"table", "view", "function"}
            or not self.migration_filenames
            or self.migration_filenames != tuple(sorted(self.migration_filenames))
            or len(set(self.migration_filenames)) != len(self.migration_filenames)
            or any(
                _MIGRATION_FILENAME.fullmatch(filename) is None
                for filename in self.migration_filenames
            )
            or (
                self.disposition == "execution_target"
                and self.reason_code != "required_by_execution_dispatch"
            )
            or (
                self.disposition == "excluded"
                and self.reason_code not in _EXCLUSION_REASONS
            )
            or self.disposition not in {"execution_target", "excluded"}
        ):
            return False
        return self.content_sha256 == _sha256(
            {
                "object_name": self.object_name,
                "object_kind": self.object_kind,
                "migration_filenames": list(self.migration_filenames),
                "disposition": self.disposition,
                "reason_code": self.reason_code,
            }
        )


@dataclass(frozen=True, slots=True)
class HostedVerificationObjectInventory:
    inventory_version: str
    migration_manifest_sha256: str
    entries: tuple[HostedMigrationObjectDisposition, ...]
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        migration_manifest_sha256: str,
        entries: tuple[HostedMigrationObjectDisposition, ...],
    ) -> HostedVerificationObjectInventory:
        if re.fullmatch(r"[0-9a-f]{64}", migration_manifest_sha256) is None:
            raise ValueError("hosted verification inventory migration hash is invalid")
        ordered_entries = tuple(sorted(entries, key=lambda item: item.object_name))
        if not ordered_entries:
            raise ValueError("hosted verification inventory is empty")
        if len({entry.object_name for entry in ordered_entries}) != len(
            ordered_entries
        ):
            raise ValueError("hosted verification inventory objects must be unique")
        if any(not entry.has_valid_content_hash() for entry in ordered_entries):
            raise ValueError("hosted verification inventory entry hash is invalid")
        version = "hosted-verification-object-inventory.v1"
        content = {
            "inventory_version": version,
            "migration_manifest_sha256": migration_manifest_sha256,
            "entries": [entry.content_sha256 for entry in ordered_entries],
        }
        return cls(
            inventory_version=version,
            migration_manifest_sha256=migration_manifest_sha256,
            entries=ordered_entries,
            content_sha256=_sha256(content),
        )

    @property
    def discovered_count(self) -> int:
        return len(self.entries)

    @property
    def execution_target_count(self) -> int:
        return sum(entry.disposition == "execution_target" for entry in self.entries)

    @property
    def excluded_count(self) -> int:
        return sum(entry.disposition == "excluded" for entry in self.entries)

    def has_valid_content_hash(self) -> bool:
        if (
            self.inventory_version != "hosted-verification-object-inventory.v1"
            or re.fullmatch(r"[0-9a-f]{64}", self.migration_manifest_sha256) is None
            or not self.entries
            or self.entries
            != tuple(sorted(self.entries, key=lambda item: item.object_name))
            or len({entry.object_name for entry in self.entries}) != len(self.entries)
            or any(not entry.has_valid_content_hash() for entry in self.entries)
        ):
            return False
        return self.content_sha256 == _sha256(
            {
                "inventory_version": self.inventory_version,
                "migration_manifest_sha256": self.migration_manifest_sha256,
                "entries": [entry.content_sha256 for entry in self.entries],
            }
        )


def build_hosted_verification_object_inventory(
    *,
    migration_paths: tuple[Path, ...],
    execution_targets: tuple[str, ...],
    exclusion_reasons: Mapping[str, str],
) -> HostedVerificationObjectInventory:
    migration_audit = audit_iros_migration_batch(migration_paths)
    if not migration_audit.passed:
        raise ValueError("hosted verification inventory migration audit failed")
    canonical_targets = tuple(sorted(execution_targets))
    if len(set(canonical_targets)) != len(canonical_targets) or any(
        _IROS_OBJECT.fullmatch(target) is None for target in canonical_targets
    ):
        raise ValueError("hosted verification inventory targets are invalid")

    declarations: dict[str, tuple[str, set[str]]] = {}
    for path in migration_paths:
        sql = strip_sql_comments_and_literals(path.read_text())
        for match in _DECLARATION.finditer(sql):
            object_name = match.group("name").lower()
            object_kind = match.group("kind").lower()
            existing = declarations.get(object_name)
            if existing is not None and existing[0] != object_kind:
                raise ValueError("hosted verification inventory object kind changed")
            filenames = existing[1] if existing is not None else set()
            filenames.add(path.name)
            declarations[object_name] = (object_kind, filenames)

    discovered = set(declarations)
    target_set = set(canonical_targets)
    exclusion_set = set(exclusion_reasons)
    if target_set - discovered:
        raise ValueError("hosted verification inventory target is undiscovered")
    if exclusion_set & target_set or exclusion_set - discovered:
        raise ValueError("hosted verification object exclusion is invalid")
    if discovered != target_set | exclusion_set:
        raise ValueError("hosted verification object disposition is incomplete")

    manifest_hash = _sha256(
        [
            {
                "filename": entry.path.name,
                "content_sha256": entry.content_sha256,
            }
            for entry in migration_audit.manifest
        ]
    )
    entries = tuple(
        HostedMigrationObjectDisposition.freeze(
            object_name=object_name,
            object_kind=object_kind,
            migration_filenames=tuple(filenames),
            disposition=(
                "execution_target" if object_name in target_set else "excluded"
            ),
            reason_code=(
                "required_by_execution_dispatch"
                if object_name in target_set
                else exclusion_reasons[object_name]
            ),
        )
        for object_name, (object_kind, filenames) in declarations.items()
    )
    return HostedVerificationObjectInventory.freeze(
        migration_manifest_sha256=manifest_hash,
        entries=entries,
    )


__all__ = [
    "HostedMigrationObjectDisposition",
    "HostedVerificationObjectInventory",
    "build_hosted_verification_object_inventory",
]
