from __future__ import annotations

import json
import os
import sys

from workers.sec.storage import (
    EvidenceStorageError,
    SupabaseStorageSettings,
)

from .client import MarketDataError, YFinanceClient, YFinanceSettings
from .storage import SupabaseMarketStore


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"missing required environment variable: {name}")
    return value


def run(argv: list[str] | None = None) -> int:
    try:
        operator_id = required_env("IROS_OPERATOR_ID")
        args = argv or []
        if len(args) != 2:
            raise ValueError("usage: python3 -m workers.market TICKER SECURITY_ID")
        ticker, security_id = args
        snapshot = YFinanceClient(YFinanceSettings()).fetch_quote(
            ticker,
            operator_id=operator_id,
            security_id=security_id,
        )
        SupabaseMarketStore(
            SupabaseStorageSettings(
                url=required_env("IROS_SUPABASE_URL"),
                secret_key=required_env("IROS_SUPABASE_SECRET_KEY"),
            )
        ).persist(snapshot)
        print(json.dumps(snapshot.as_dict(), indent=2, sort_keys=True))
        return 0
    except (EvidenceStorageError, MarketDataError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
