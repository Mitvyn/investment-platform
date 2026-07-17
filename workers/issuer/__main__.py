from __future__ import annotations

import argparse
import json
import os
import sys

from workers.sec.storage import EvidenceStorageError, SupabaseStorageSettings

from .collector import IssuerCollector, IssuerCollectorError
from .models import PassageRequest, ReleaseRequest
from .storage import SupabaseIssuerStore
from .tracer import build_issuer_context


RXRX_Q1_2026 = ReleaseRequest(
    ticker="RXRX",
    company_name="Recursion Pharmaceuticals, Inc.",
    release_type="earnings",
    title=(
        "Recursion Reports First Quarter 2026 Financial Results and "
        "Provides Business Updates"
    ),
    published_at="2026-05-06T07:05:00-04:00",
    source_url=(
        "https://ir.recursion.com/news-releases/news-release-details/"
        "recursion-reports-first-quarter-financial-results-and-provides"
    ),
    passages=(
        PassageRequest(
            key="cash",
            locator="Q1 2026 financial results, cash and cash equivalents",
            expected_text=(
                "Cash, cash equivalents and restricted cash were $665.2 million "
                "as of March 31, 2026 compared to $753.9 million as of "
                "December 31, 2025."
            ),
        ),
        PassageRequest(
            key="operating_cash",
            locator="Q1 2026 financial results, operating cash flow",
            expected_text=(
                "Net cash used in operating activities was $81.1 million for "
                "the three months ended March 31, 2026, compared to net cash "
                "used in operating activities of $132.0 million for the three "
                "months ended March 31, 2025."
            ),
        ),
        PassageRequest(
            key="runway_risk",
            locator="Q1 2026 financial results, cash position",
            expected_text=(
                "Based on current operating plans and with no additional "
                "financing, the Company continues to expect its cash runway "
                "to extend into early 2028."
            ),
        ),
        PassageRequest(
            key="catalyst",
            locator="Expected upcoming milestones, REC-4881 (MEK1/2)",
            expected_text=(
                "REC-4881 (MEK1/2): Regulatory update expected in 2H26"
            ),
        ),
    ),
)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"missing required environment variable: {name}")
    return value


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m workers.issuer")
    parser.add_argument(
        "command",
        choices=("ingest-rxrx-q1-2026", "verify-rxrx-q1-2026"),
    )
    command = parser.parse_args(argv).command

    try:
        context = build_issuer_context(
            IssuerCollector().fetch_release(RXRX_Q1_2026),
            operator_id=required_env("IROS_OPERATOR_ID"),
        )
        store = SupabaseIssuerStore(
            SupabaseStorageSettings(
                url=required_env("IROS_SUPABASE_URL"),
                secret_key=required_env("IROS_SUPABASE_SECRET_KEY"),
            )
        )
        if command == "ingest-rxrx-q1-2026":
            store.persist(context)
            result = context.as_dict()
        else:
            result = {
                "context": context.as_dict(),
                "hostedRows": store.verify(context),
            }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (EvidenceStorageError, IssuerCollectorError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
