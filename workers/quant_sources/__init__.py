"""Provider-specific adapters into the provider-neutral Quant receipt boundary."""

from .providers import (
    MoomooHistoryBar,
    MoomooHistoryPayload,
    MoomooQuantSource,
    YFinanceQuantSource,
)
from .transports import (
    BoundedCaller,
    HistoricalTransport,
    HistoryBar,
    HistoryPayload,
    RateLimit,
    RetryPolicy,
    TransientTransportError,
    TransportBlockedError,
    TransportError,
)

__all__ = [
    "BoundedCaller",
    "HistoricalTransport",
    "HistoryBar",
    "HistoryPayload",
    "MoomooHistoryBar",
    "MoomooHistoryPayload",
    "MoomooQuantSource",
    "RateLimit",
    "RetryPolicy",
    "TransientTransportError",
    "TransportBlockedError",
    "TransportError",
    "YFinanceQuantSource",
]
