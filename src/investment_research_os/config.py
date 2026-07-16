from __future__ import annotations

import os
import re
from dataclasses import dataclass


class ConfigError(ValueError):
    """Raised when required runtime configuration is missing."""


APPROVAL_VALUES = {"1", "true", "yes", "on"}
USER_AGENT_PATTERN = re.compile(
    r"^[A-Za-z0-9._-]+:[A-Za-z0-9._-]+:[A-Za-z0-9._-]+ "
    r"\(by /u/[A-Za-z0-9_-]{3,20}\)$"
)
USER_AGENT_PLACEHOLDERS = {"changeme", "your_reddit_username"}


@dataclass(frozen=True, slots=True)
class RedditSettings:
    client_id: str
    client_secret: str
    user_agent: str
    token_url: str = "https://www.reddit.com/api/v1/access_token"
    api_base_url: str = "https://oauth.reddit.com"
    timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> "RedditSettings":
        approval = os.environ.get("REDDIT_API_APPROVED", "").strip().lower()
        if approval not in APPROVAL_VALUES:
            raise ConfigError(
                "Reddit API access is disabled; set REDDIT_API_APPROVED=true "
                "only after Reddit grants explicit approval"
            )

        missing = [
            name
            for name in (
                "REDDIT_CLIENT_ID",
                "REDDIT_CLIENT_SECRET",
                "REDDIT_USER_AGENT",
            )
            if not os.environ.get(name, "").strip()
        ]
        if missing:
            names = ", ".join(missing)
            raise ConfigError(f"missing required environment variables: {names}")

        user_agent = os.environ["REDDIT_USER_AGENT"].strip()
        if not USER_AGENT_PATTERN.fullmatch(user_agent) or any(
            placeholder in user_agent.lower() for placeholder in USER_AGENT_PLACEHOLDERS
        ):
            raise ConfigError(
                "REDDIT_USER_AGENT must match "
                "<platform>:<app ID>:<version> (by /u/<reddit username>)"
            )

        return cls(
            client_id=os.environ["REDDIT_CLIENT_ID"].strip(),
            client_secret=os.environ["REDDIT_CLIENT_SECRET"].strip(),
            user_agent=user_agent,
        )
