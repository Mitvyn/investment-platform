from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RedditPost:
    id: str
    subreddit: str
    title: str
    permalink: str
    created_utc: float
    score: int
    comment_count: int
    retrieved_at: str
    body: str | None = None
