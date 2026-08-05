from __future__ import annotations

from datetime import datetime
from typing import Callable

from workers.official_sources.collector import (
    OfficialBytesTransport,
    OfficialEvidenceAdapter,
)


class FDARegulatoryEvidenceAdapter(OfficialEvidenceAdapter):
    def __init__(
        self,
        *,
        allowed_hosts: tuple[str, ...],
        transport: OfficialBytesTransport,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not allowed_hosts or any(
            (
                host != host.lower()
                or (host != "fda.gov" and not host.endswith(".fda.gov"))
                or "*" in host
                or "/" in host
                or ":" in host
            )
            for host in allowed_hosts
        ):
            raise ValueError("FDA host allowlist must contain explicit fda.gov hosts")
        super().__init__(
            source_class="regulatory",
            allowed_hosts=allowed_hosts,
            transport=transport,
            clock=clock,
        )


__all__ = ["FDARegulatoryEvidenceAdapter"]
