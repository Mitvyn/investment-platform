from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .acquisition import (
    PrimarySourceAcquisitionResult,
    SpacedBytesTransport,
    acquire_primary_source_capture,
)
from .http import CurlCffiBytesTransport
from .models import PrimarySourceRequest
from .plans import load_primary_source_plan


class PrimarySourceCliError(RuntimeError):
    """Raised when a capture command cannot preserve its immutable contract."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m workers.primary_sources")
    subcommands = parser.add_subparsers(dest="command", required=True)
    acquire = subcommands.add_parser("acquire")
    acquire.add_argument("--plan", required=True)
    acquire.add_argument("--ticker", required=True)
    acquire.add_argument("--operator-id", required=True)
    acquire.add_argument("--capture-id", required=True)
    acquire.add_argument("--revision", required=True, type=int)
    acquire.add_argument(
        "--trusted-issuer-host",
        action="append",
        required=True,
        dest="trusted_issuer_hosts",
    )
    acquire.add_argument("--output", required=True)
    acquire.add_argument("--timeout-seconds", type=float, default=20.0)
    acquire.add_argument("--minimum-interval-seconds", type=float, default=0.2)
    return parser


def _write_immutable(path: Path, body: bytes) -> None:
    if path.exists():
        if path.is_file() and path.read_bytes() == body:
            return
        raise PrimarySourceCliError("capture output already contains other bytes")
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(body)
        temporary.flush()
        temporary_path = Path(temporary.name)
    try:
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def run(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] = os.environ,
    acquire: Callable[..., PrimarySourceAcquisitionResult] = (
        acquire_primary_source_capture
    ),
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    transport: Any | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if args.command != "acquire":
        raise PrimarySourceCliError("primary-source command is unsupported")
    source_plan = Path(args.plan).read_bytes()
    plan = load_primary_source_plan(source_plan)
    if plan.revision != args.revision:
        raise PrimarySourceCliError("capture revision does not match source plan")
    user_agent = environ.get("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise PrimarySourceCliError("SEC_USER_AGENT is required")
    source_transport = transport
    if source_transport is None:
        source_transport = SpacedBytesTransport(
            CurlCffiBytesTransport(args.timeout_seconds),
            user_agent=user_agent,
            minimum_interval_seconds=args.minimum_interval_seconds,
        )
    request = PrimarySourceRequest(
        operator_id=args.operator_id,
        security_id=plan.security_id,
        cik=plan.cik,
        issuer_name=plan.issuer_name,
        primary_listing_exchange=plan.primary_listing_exchange,
        as_of_cutoff=plan.effective_at,
    )
    result = acquire(
        request=request,
        ticker=args.ticker.upper(),
        source_plan=source_plan,
        trusted_issuer_hosts=tuple(
            sorted({host.casefold() for host in args.trusted_issuer_hosts})
        ),
        user_agent=user_agent,
        transport=source_transport,
        clock=clock,
        capture_id=args.capture_id,
        revision=args.revision,
        assembled_at=None,
    )
    output = Path(args.output)
    _write_immutable(output, result.archive)
    print(
        json.dumps(
            {
                "archive_sha256": hashlib.sha256(result.archive).hexdigest(),
                "clinical_study_count": result.clinical_study_count,
                "companyfact_count": result.companyfact_count,
                "issuer_source_count": result.issuer_source_count,
                "output": str(output),
                "regulatory_source_count": result.regulatory_source_count,
                "selected_accessions": list(result.selected_accessions),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())


__all__ = ["PrimarySourceCliError", "run"]
