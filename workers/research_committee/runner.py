from __future__ import annotations

import math
import time
from typing import Callable, Protocol


class ResearchCommitteeWorker(Protocol):
    def run_once(self) -> bool: ...


def validate_poll_interval_seconds(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.1 <= value <= 60
    ):
        raise ValueError("poll interval must be between 0.1 and 60 seconds")
    return float(value)


class ResearchCommitteeRunner:
    def __init__(
        self,
        worker: ResearchCommitteeWorker,
        *,
        poll_interval_seconds: float,
        sleeper: Callable[[float], object] = time.sleep,
    ) -> None:
        self._worker = worker
        self._poll_interval_seconds = validate_poll_interval_seconds(
            poll_interval_seconds
        )
        self._sleeper = sleeper

    def run(
        self,
        *,
        once: bool,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        if once:
            self._worker.run_once()
            return
        while not stop_requested():
            if not self._worker.run_once():
                self._sleeper(self._poll_interval_seconds)


__all__ = [
    "ResearchCommitteeRunner",
    "ResearchCommitteeWorker",
    "validate_poll_interval_seconds",
]
