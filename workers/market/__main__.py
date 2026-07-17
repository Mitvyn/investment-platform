from __future__ import annotations

import json
import os
import sys

from workers.sec.storage import (
    EvidenceStorageError,
    SupabaseStorageSettings,
)

from .client import MarketDataError, TwelveDataClient, TwelveDataSettings
from .storage import SupabaseMarketStore


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"missing required environment variable: {name}")
    return value


def run() -> int:
    try:
        snapshot = TwelveDataClient(
            TwelveDataSettings(api_key=required_env("TWELVE_DATA_API_KEY"))
        ).fetch_quote(
            "RXRX",
            operator_id=required_env("IROS_OPERATOR_ID"),
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
    raise SystemExit(run())
