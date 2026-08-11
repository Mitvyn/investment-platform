from __future__ import annotations

import re


_DESIGNATION_PATTERN = re.compile(
    r"\b(?:orphan\s+drug|designat(?:ed|ion))\b",
    re.IGNORECASE,
)


def has_programme_designation_link(
    *,
    text_groups: tuple[tuple[str, ...], ...],
    program_names: tuple[str, ...],
) -> bool:
    normalized_names = tuple(
        dict.fromkeys(name.strip().casefold() for name in program_names if name.strip())
    )
    if not normalized_names:
        return False
    for texts in text_groups:
        combined_text = " ".join(texts)
        normalized_text = combined_text.casefold()
        if (
            any(name in normalized_text for name in normalized_names)
            and _DESIGNATION_PATTERN.search(combined_text) is not None
        ):
            return True
    return False


__all__ = ["has_programme_designation_link"]
