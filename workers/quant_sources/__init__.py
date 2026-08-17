"""Provider-specific adapters into the provider-neutral Quant receipt boundary."""

from .providers import (
    MoomooHistoryBar,
    MoomooHistoryPayload,
    MoomooQuantSource,
    YFinanceQuantSource,
)

__all__ = [
    "MoomooHistoryBar",
    "MoomooHistoryPayload",
    "MoomooQuantSource",
    "YFinanceQuantSource",
]
