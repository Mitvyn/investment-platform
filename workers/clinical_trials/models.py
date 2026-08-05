from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClinicalTrialSearchIdentity:
    program_name: str
    search_terms: tuple[str, ...]
    allowed_sponsor_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        program_name = self.program_name.strip()
        if not program_name:
            raise ValueError("clinical trial program name is required")
        terms = tuple(term.strip() for term in self.search_terms)
        if not terms or any(not term for term in terms):
            raise ValueError("clinical trial search terms are required")
        if len(terms) > 20:
            raise ValueError("clinical trial search terms exceed limit")
        if len(set(terms)) != len(terms):
            raise ValueError("clinical trial search terms must be unique")
        sponsors = tuple(
            sponsor.strip() for sponsor in self.allowed_sponsor_names
        )
        if any(not sponsor for sponsor in sponsors):
            raise ValueError("clinical trial sponsor name is invalid")
        if len(sponsors) > 20:
            raise ValueError("clinical trial sponsor names exceed limit")
        if len(set(sponsors)) != len(sponsors):
            raise ValueError("clinical trial sponsor names must be unique")
        object.__setattr__(self, "program_name", program_name)
        object.__setattr__(self, "search_terms", terms)
        object.__setattr__(self, "allowed_sponsor_names", sponsors)


__all__ = ["ClinicalTrialSearchIdentity"]
