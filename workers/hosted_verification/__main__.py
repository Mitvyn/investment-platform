from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from investment_research_os.hosted_verification_v3 import (
    build_default_iros_hosted_execution_contract,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m workers.hosted_verification")
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run = subparsers.add_parser("dry-run")
    dry_run.add_argument("--migration-root", required=True, type=Path)
    return parser


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def run(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    del environment
    arguments = _parser().parse_args(argv)
    migration_paths = tuple(sorted(arguments.migration_root.glob("*_iros_*.sql")))
    if not migration_paths:
        _emit(
            {
                "error": "hosted_verification_dry_run_failed",
                "reason": "migration_batch_empty",
            }
        )
        return 2
    try:
        contract = build_default_iros_hosted_execution_contract(
            migration_paths=migration_paths,
        )
    except (OSError, ValueError):
        _emit(
            {
                "error": "hosted_verification_dry_run_failed",
                "reason": "execution_contract_invalid",
            }
        )
        return 2
    _emit(
        {
            "connection_attempted": False,
            "content_sha256": contract.content_sha256,
            "contract_version": contract.contract_version,
            "dispatch_count": len(contract.dispatches),
            "dispatch_registry_sha256": contract.dispatch_registry_sha256,
            "execution_target_manifest_sha256": (
                contract.execution_target_manifest_sha256
            ),
            "fixture_count": len(contract.fixtures),
            "fixture_set_sha256": contract.fixture_set_sha256,
            "migration_count": len(migration_paths),
            "migration_manifest_sha256": contract.migration_manifest_sha256,
            "plan_sha256": contract.plan_sha256,
            "plan_target_manifest_sha256": contract.plan_target_manifest_sha256,
            "probe_count": len(contract.dispatches),
            "required_scopes": list(contract.required_scopes),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(environment=os.environ))
