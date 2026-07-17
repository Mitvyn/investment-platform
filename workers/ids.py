from __future__ import annotations

import uuid


TRACE_NAMESPACE = uuid.UUID("791c6c1a-c93f-4b41-889e-7e48032c9d70")


def stable_id(operator_id: str, record_type: str, identity: str) -> str:
    return str(
        uuid.uuid5(
            TRACE_NAMESPACE,
            f"{operator_id}:{record_type}:{identity}",
        )
    )
