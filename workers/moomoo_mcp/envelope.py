"""Strict helpers for bounded nested documented result wrappers."""

from __future__ import annotations

from typing import Mapping


def unwrap_expected_mapping(value: object, expected_key: str) -> Mapping[str, object] | None:
    """Return expected wrapper directly or through one explicit outer map."""

    if not isinstance(value, Mapping) or not value:
        return None
    if set(value) == {expected_key}:
        return value
    if len(value) != 1:
        return None
    nested = next(iter(value.values()))
    if isinstance(nested, Mapping) and nested and set(nested) == {expected_key}:
        return nested
    return None


__all__ = ["unwrap_expected_mapping"]
