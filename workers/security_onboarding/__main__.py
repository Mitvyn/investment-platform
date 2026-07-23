from __future__ import annotations

import os
import sys
import time

from workers.market.client import YFinanceClient, YFinanceSettings
from workers.market.storage import SupabaseMarketStore
from workers.sec.collector import SecCollectorError, SecSettings
from workers.sec.storage import EvidenceStorageError, SupabaseStorageSettings
from workers.security_registry.client import SecurityRegistryClient
from workers.security_registry.storage import SupabaseSecurityRegistryStore

from .storage import SupabaseSecurityJobStore
from .worker import SecurityOnboardingWorker


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"missing required environment variable: {name}")
    return value


def build_worker() -> SecurityOnboardingWorker:
    worker_id = required_env("IROS_WORKER_ID")
    settings = SupabaseStorageSettings(
        url=required_env("IROS_SUPABASE_URL"),
        secret_key=required_env("IROS_SUPABASE_SECRET_KEY"),
    )
    return SecurityOnboardingWorker(
        worker_id=worker_id,
        jobs=SupabaseSecurityJobStore(settings),
        registry=SecurityRegistryClient(
            SecSettings(user_agent=required_env("SEC_USER_AGENT"))
        ),
        registry_store=SupabaseSecurityRegistryStore(settings),
        market=YFinanceClient(YFinanceSettings()),
        market_store=SupabaseMarketStore(settings),
    )


def run(argv: list[str] | None = None) -> int:
    try:
        args = argv or []
        if args not in (["run-once"], ["run"]):
            raise ValueError(
                "usage: python3 -m workers.security_onboarding run-once|run"
            )
        worker = build_worker()
        if args == ["run-once"]:
            worker.run_once()
            return 0
        while True:
            if not worker.run_once():
                time.sleep(2)
    except KeyboardInterrupt:
        return 0
    except (EvidenceStorageError, SecCollectorError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except Exception:
        print("error: security onboarding worker failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
