"""Acquisition boundary that builds Quant receipts from source payloads.

Depends on ``investment_research_os.quant``. Nothing in Quant depends on this,
which is what keeps Quant core provider-neutral.
"""

from investment_research_os.quant_sources.adapter import (
    ADAPTER_VERSION,
    SourceSnapshot,
    acquire_point_in_time_dataset,
    payload_sha256,
    revalidate_source_snapshot,
)

__all__ = [
    "ADAPTER_VERSION",
    "SourceSnapshot",
    "acquire_point_in_time_dataset",
    "payload_sha256",
    "revalidate_source_snapshot",
]
