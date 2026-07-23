from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from workers.sec.storage import EvidenceStorageError, SupabaseStorageSettings

from .models import build_holding_snapshot
from .storage import SupabaseHoldingsStore


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"missing required environment variable: {name}")
    return value


def run(argv: list[str] | None = None) -> int:
    try:
        args = argv or []
        if len(args) != 2 or args[0] != "import-json":
            raise ValueError(
                "usage: python3 -m workers.holdings import-json PRIVATE_FILE"
            )
        payload = json.loads(Path(args[1]).read_text())
        if not isinstance(payload, dict):
            raise ValueError("holdings import must be a JSON object")
        snapshot = build_holding_snapshot(
            payload,
            operator_id=required_env("IROS_OPERATOR_ID"),
            captured_at=datetime.now(UTC),
        )
        SupabaseHoldingsStore(
            SupabaseStorageSettings(
                url=required_env("IROS_SUPABASE_URL"),
                secret_key=required_env("IROS_SUPABASE_SECRET_KEY"),
            )
        ).persist(snapshot)
        print(
            json.dumps(
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "position_count": snapshot.position_count,
                    "content_sha256": snapshot.content_sha256,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (
        EvidenceStorageError,
        json.JSONDecodeError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
