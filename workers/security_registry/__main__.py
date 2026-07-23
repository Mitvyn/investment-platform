from __future__ import annotations

import json
import os
import sys

from workers.sec.collector import SecCollectorError, SecSettings
from workers.sec.storage import EvidenceStorageError, SupabaseStorageSettings

from .client import SecurityRegistryClient, SecurityRegistryError
from .storage import SupabaseSecurityRegistryStore


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"missing required environment variable: {name}")
    return value


def run(argv: list[str] | None = None) -> int:
    try:
        args = argv or []
        if len(args) != 1:
            raise ValueError("usage: python3 -m workers.security_registry TICKER")
        security = SecurityRegistryClient(
            SecSettings(user_agent=required_env("SEC_USER_AGENT"))
        ).resolve(
            args[0],
            operator_id=required_env("IROS_OPERATOR_ID"),
        )
        SupabaseSecurityRegistryStore(
            SupabaseStorageSettings(
                url=required_env("IROS_SUPABASE_URL"),
                secret_key=required_env("IROS_SUPABASE_SECRET_KEY"),
            )
        ).persist(security)
        print(json.dumps(security.as_dict(), indent=2, sort_keys=True))
        return 0
    except (
        EvidenceStorageError,
        SecCollectorError,
        SecurityRegistryError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
