from __future__ import annotations

import argparse
import json
import os
import sys

from .collector import SecCollector, SecCollectorError, SecSettings
from .models import FilingRequest
from .storage import (
    EvidenceStorageError,
    SupabaseEvidenceStore,
    SupabaseStorageSettings,
)
from .tracer import build_evidence_trace

RXRX_Q2_2025 = FilingRequest(
    ticker="RXRX",
    company_name="Recursion Pharmaceuticals, Inc.",
    cik="1601830",
    accession_number="0001601830-25-000127",
    primary_document="rxrx-20250630.htm",
    filing_form="10-Q",
    filed_at="2025-08-05",
    period_end="2025-06-30",
    passage_locator=(
        "Part I, Item 2, Liquidity and Capital Resources, Sources of Liquidity"
    ),
    expected_passage=(
        "Cash and cash equivalents totaled $525.1 million and $594.3 million "
        "as of June 30, 2025 and December 31, 2024, respectively."
    ),
    claim_text=(
        "RXRX reported $525.1 million in cash and cash equivalents "
        "as of June 30, 2025."
    ),
)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"missing required environment variable: {name}")
    return value


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m workers.sec")
    parser.add_argument(
        "command",
        choices=(
            "ingest-rxrx-q2-2025",
            "verify-rxrx-q2-2025",
        ),
    )
    command = parser.parse_args(argv).command

    try:
        sec_user_agent = required_env("SEC_USER_AGENT")
        operator_id = required_env("IROS_OPERATOR_ID")
        supabase_url = required_env("IROS_SUPABASE_URL")
        secret_key = required_env("IROS_SUPABASE_SECRET_KEY")

        collector = SecCollector(SecSettings(user_agent=sec_user_agent))
        trace = build_evidence_trace(
            collector.fetch_filing(RXRX_Q2_2025),
            operator_id=operator_id,
        )
        store = SupabaseEvidenceStore(
            SupabaseStorageSettings(
                url=supabase_url,
                secret_key=secret_key,
            )
        )
        if command == "ingest-rxrx-q2-2025":
            store.persist(trace)
            result = trace.dashboard_record()
        else:
            result = {
                "evidence": trace.dashboard_record(),
                "hostedRows": store.verify(trace),
            }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (
        EvidenceStorageError,
        SecCollectorError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(run())
