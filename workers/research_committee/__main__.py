from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
import sys
import time
from typing import TextIO

from .runner import (
    ResearchCommitteeRunner,
    ResearchCommitteeWorker,
    validate_poll_interval_seconds,
)


_USAGE = (
    "usage: python3 -m workers.research_committee [--once] [--poll-seconds 0.1..60]"
)
_REQUIRED_ENVIRONMENT = (
    "IROS_WORKER_ID",
    "IROS_SUPABASE_URL",
    "IROS_SUPABASE_SECRET_KEY",
    "SEC_USER_AGENT",
    "MASSIVE_API_KEY",
)
_MISSING_PRODUCTION_COMPOSITION = (
    "nasdaq_trader_live_contract_verification",
    "personal_research_market_activation",
    "approved_model_provider_activation",
    "live_execution_authorization_manifest",
    "hosted_isolation_verification",
)


class ResearchCommitteeStartupError(ValueError):
    """Raised when a complete, safe worker cannot be started."""


@dataclass(frozen=True, slots=True)
class ResearchCommitteeStartupConfiguration:
    worker_id: str
    supabase_url: str
    supabase_secret_key: str
    sec_user_agent: str
    massive_api_key: str

    def __repr__(self) -> str:
        return (
            "ResearchCommitteeStartupConfiguration("
            f"worker_id={self.worker_id!r}, "
            f"supabase_url={self.supabase_url!r}, "
            "supabase_secret_key=<redacted>, "
            f"sec_user_agent={self.sec_user_agent!r}, "
            "massive_api_key=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class _CliOptions:
    once: bool
    poll_interval_seconds: float


def load_startup_configuration(
    environment: Mapping[str, str],
) -> ResearchCommitteeStartupConfiguration:
    values = {name: environment.get(name, "").strip() for name in _REQUIRED_ENVIRONMENT}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ResearchCommitteeStartupError(
            "missing required environment variables: " + ", ".join(missing)
        )
    return ResearchCommitteeStartupConfiguration(
        worker_id=values["IROS_WORKER_ID"],
        supabase_url=values["IROS_SUPABASE_URL"],
        supabase_secret_key=values["IROS_SUPABASE_SECRET_KEY"],
        sec_user_agent=values["SEC_USER_AGENT"],
        massive_api_key=values["MASSIVE_API_KEY"],
    )


def build_worker(
    configuration: ResearchCommitteeStartupConfiguration,
) -> ResearchCommitteeWorker:
    del configuration
    raise ResearchCommitteeStartupError(
        "research committee production composition unavailable: "
        + ", ".join(_MISSING_PRODUCTION_COMPOSITION)
    )


def _parse_options(argv: list[str]) -> _CliOptions:
    once = False
    poll_interval_seconds = 2.0
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--once" and not once:
            once = True
            index += 1
            continue
        if argument == "--poll-seconds" and index + 1 < len(argv):
            try:
                poll_interval_seconds = float(argv[index + 1])
            except ValueError as error:
                raise ResearchCommitteeStartupError(_USAGE) from error
            index += 2
            continue
        raise ResearchCommitteeStartupError(_USAGE)
    return _CliOptions(
        once=once,
        poll_interval_seconds=validate_poll_interval_seconds(poll_interval_seconds),
    )


def run(
    argv: list[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    worker_factory: Callable[
        [ResearchCommitteeStartupConfiguration],
        ResearchCommitteeWorker,
    ] = build_worker,
    stderr: TextIO = sys.stderr,
    sleeper: Callable[[float], object] = time.sleep,
    stop_requested: Callable[[], bool] = lambda: False,
) -> int:
    try:
        options = _parse_options(argv or [])
        configuration = load_startup_configuration(
            os.environ if environment is None else environment
        )
        worker = worker_factory(configuration)
        ResearchCommitteeRunner(
            worker,
            poll_interval_seconds=options.poll_interval_seconds,
            sleeper=sleeper,
        ).run(once=options.once, stop_requested=stop_requested)
        return 0
    except KeyboardInterrupt:
        return 0
    except (ResearchCommitteeStartupError, ValueError) as error:
        print(f"error: {error}", file=stderr)
        return 2
    except Exception:
        print("error: research committee worker failed", file=stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
