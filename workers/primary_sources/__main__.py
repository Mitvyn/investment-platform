from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
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
from .replay import PrimarySourceReplayResult, replay_primary_source_capture
from .storage import FilePrimarySourceCaptureRepository, PrimarySourceStorageError


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
    for name in ("verify", "accept"):
        verification = subcommands.add_parser(name)
        verification.add_argument("--plan", required=True)
        verification.add_argument("--capture", required=True)
        verification.add_argument("--ticker", required=True)
        verification.add_argument("--operator-id", required=True)
        verification.add_argument("--as-of-cutoff", required=True)
        verification.add_argument(
            "--trusted-issuer-host",
            action="append",
            required=True,
            dest="trusted_issuer_hosts",
        )
        if name == "accept":
            verification.add_argument("--capture-root", required=True)
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


def _utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PrimarySourceCliError("as-of cutoff is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PrimarySourceCliError("as-of cutoff must include timezone")
    return parsed.astimezone(UTC)


def run(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] = os.environ,
    acquire: Callable[..., PrimarySourceAcquisitionResult] = (
        acquire_primary_source_capture
    ),
    replay: Callable[..., PrimarySourceReplayResult] = replay_primary_source_capture,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    transport: Any | None = None,
) -> int:
    args = _parser().parse_args(argv)
    source_plan = Path(args.plan).read_bytes()
    plan = load_primary_source_plan(source_plan)
    if args.command in {"accept", "verify"}:
        user_agent = environ.get("SEC_USER_AGENT", "").strip()
        if not user_agent:
            raise PrimarySourceCliError("SEC_USER_AGENT is required")
        request = PrimarySourceRequest(
            operator_id=args.operator_id,
            security_id=plan.security_id,
            cik=plan.cik,
            issuer_name=plan.issuer_name,
            primary_listing_exchange=plan.primary_listing_exchange,
            as_of_cutoff=_utc_timestamp(args.as_of_cutoff),
        )
        try:
            raw_archive = Path(args.capture).read_bytes()
            result = replay(
                raw_archive,
                request=request,
                ticker=args.ticker.upper(),
                sec_user_agent=user_agent,
                trusted_issuer_hosts=tuple(
                    sorted({host.casefold() for host in args.trusted_issuer_hosts})
                ),
                accepted_at=clock,
            )
        except (RuntimeError, ValueError):
            raise PrimarySourceCliError("capture verification failed") from None
        if result.capture.plan.content_hash != plan.content_hash:
            raise PrimarySourceCliError("capture does not match requested source plan")
        if args.command == "accept":
            capture_root = Path(args.capture_root).expanduser()
            if not capture_root.is_absolute():
                raise PrimarySourceCliError("capture root must be absolute")
            try:
                persisted = FilePrimarySourceCaptureRepository(
                    capture_root
                ).save_capture(result.capture, raw_archive)
            except (OSError, PrimarySourceStorageError):
                raise PrimarySourceCliError("capture acceptance failed") from None
            print(
                json.dumps(
                    {
                        "archive_sha256": persisted.package_sha256,
                        "capture_content_hash": persisted.capture_content_hash,
                        "capture_id": persisted.capture_id,
                        "capture_revision": persisted.capture_revision,
                        "contract_version": "primary_source_capture_acceptance.v1",
                        "security_id": persisted.security_id,
                        "status": "accepted",
                    },
                    sort_keys=True,
                )
            )
            return 0
        print(
            json.dumps(
                {
                    "archive_sha256": result.capture.receipt.package_sha256,
                    "capture_content_hash": result.capture.content_hash,
                    "capture_id": result.capture.capture_id,
                    "capture_revision": result.capture.revision,
                    "contract_version": ("primary_source_capture_verification.v1"),
                    "plan_content_hash": result.capture.plan.content_hash,
                    "response_count": len(result.capture.responses),
                    "sec_passage_count": len(result.sec_passages),
                    "security_id": request.security_id,
                    "status": "verified",
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command != "acquire":
        raise PrimarySourceCliError("primary-source command is unsupported")
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


def main(
    argv: Sequence[str] | None = None,
    **run_options: Any,
) -> int:
    try:
        return run(argv, **run_options)
    except PrimarySourceCliError as error:
        print(
            json.dumps(
                {"error": str(error), "status": "failed"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["PrimarySourceCliError", "main", "run"]
