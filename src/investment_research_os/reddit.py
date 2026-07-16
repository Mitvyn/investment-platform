from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from .config import RedditSettings
from .models import RedditPost

SUBREDDIT_PATTERN = re.compile(r"^[A-Za-z0-9_]{2,21}$")


class RedditApiError(RuntimeError):
    """Raised when Reddit returns an error or malformed response."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class JsonResponse:
    payload: Any
    status: int
    headers: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class RateLimit:
    remaining: float | None
    reset_seconds: float | None


class JsonTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        form: Mapping[str, str] | None = None,
    ) -> JsonResponse: ...


class UrllibJsonTransport:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        form: Mapping[str, str] | None = None,
    ) -> JsonResponse:
        body = urlencode(form).encode() if form is not None else None
        request_headers = dict(headers)
        if form is not None:
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"

        request = Request(url, data=body, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = self._decode_json(response.read())
                return JsonResponse(
                    payload=payload,
                    status=response.status,
                    headers=dict(response.headers.items()),
                )
        except HTTPError as error:
            payload = self._decode_json(error.read(), allow_invalid=True)
            detail = self._error_detail(payload, fallback=str(error.reason))
            raise RedditApiError(
                f"Reddit API returned HTTP {error.code}: {detail}",
                status=error.code,
            ) from error
        except URLError as error:
            raise RedditApiError("could not reach Reddit API") from error

    @staticmethod
    def _decode_json(raw: bytes, *, allow_invalid: bool = False) -> Any:
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            if allow_invalid:
                return None
            raise RedditApiError("Reddit API returned invalid JSON") from error

    @staticmethod
    def _error_detail(payload: Any, *, fallback: str) -> str:
        if isinstance(payload, dict):
            for key in ("message", "error"):
                value = payload.get(key)
                if value:
                    return str(value)
        return fallback


class RedditClient:
    def __init__(
        self,
        settings: RedditSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self.last_rate_limit: RateLimit | None = None

    def fetch_new_posts(
        self,
        subreddit: str,
        *,
        limit: int = 10,
        include_body: bool = False,
    ) -> list[RedditPost]:
        subreddit = subreddit.strip()
        if not SUBREDDIT_PATTERN.fullmatch(subreddit):
            raise ValueError(
                "subreddit must contain 2-21 letters, numbers, or underscores"
            )
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        query = urlencode({"limit": limit, "raw_json": 1})
        url = f"{self.settings.api_base_url}/r/{subreddit}/new?{query}"
        response = self.transport.request_json(
            "GET",
            url,
            headers=self._oauth_headers(),
        )
        self._record_rate_limit(response.headers)
        children = self._listing_children(response.payload)
        retrieved_at = datetime.now(UTC).isoformat()
        return [
            self._map_post(child, retrieved_at, include_body=include_body)
            for child in children
        ]

    def _oauth_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._get_access_token()}",
            "User-Agent": self.settings.user_agent,
        }

    def _get_access_token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        credentials = f"{self.settings.client_id}:{self.settings.client_secret}"
        basic_token = base64.b64encode(credentials.encode()).decode("ascii")
        response = self.transport.request_json(
            "POST",
            self.settings.token_url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {basic_token}",
                "User-Agent": self.settings.user_agent,
            },
            form={"grant_type": "client_credentials"},
        )
        if not isinstance(response.payload, dict):
            raise RedditApiError("Reddit OAuth returned malformed JSON")

        access_token = response.payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise RedditApiError(
                "Reddit OAuth response did not include an access token"
            )

        expires_in = response.payload.get("expires_in", 3600)
        try:
            lifetime = max(0, int(expires_in) - 60)
        except (TypeError, ValueError) as error:
            raise RedditApiError(
                "Reddit OAuth returned invalid token expiry"
            ) from error

        self._access_token = access_token
        self._token_expires_at = now + lifetime
        return access_token

    def _record_rate_limit(self, headers: Mapping[str, str]) -> None:
        normalized = {key.lower(): value for key, value in headers.items()}

        def parse(name: str) -> float | None:
            value = normalized.get(name)
            try:
                return float(value) if value is not None else None
            except ValueError:
                return None

        self.last_rate_limit = RateLimit(
            remaining=parse("x-ratelimit-remaining"),
            reset_seconds=parse("x-ratelimit-reset"),
        )
        if (
            self.last_rate_limit.remaining is not None
            and self.last_rate_limit.remaining <= 0
        ):
            reset = self.last_rate_limit.reset_seconds
            suffix = f" Retry after about {reset:.0f} seconds." if reset else ""
            raise RedditApiError(
                f"Reddit API rate limit exhausted.{suffix}", status=429
            )

    @staticmethod
    def _listing_children(payload: Any) -> list[Mapping[str, Any]]:
        try:
            children = payload["data"]["children"]
        except (KeyError, TypeError) as error:
            raise RedditApiError("Reddit listing response was malformed") from error
        if not isinstance(children, list) or not all(
            isinstance(child, dict) for child in children
        ):
            raise RedditApiError("Reddit listing response contained invalid children")
        return children

    @staticmethod
    def _map_post(
        child: Mapping[str, Any],
        retrieved_at: str,
        *,
        include_body: bool,
    ) -> RedditPost:
        data = child.get("data")
        if not isinstance(data, dict):
            raise RedditApiError("Reddit listing child was malformed")

        raw_permalink = str(data.get("permalink", ""))
        return RedditPost(
            id=str(data.get("id", "")),
            subreddit=str(data.get("subreddit", "")),
            title=str(data.get("title", "")),
            permalink=urljoin("https://www.reddit.com", raw_permalink),
            created_utc=float(data.get("created_utc", 0)),
            score=int(data.get("score", 0)),
            comment_count=int(data.get("num_comments", 0)),
            retrieved_at=retrieved_at,
            body=str(data.get("selftext", "")) if include_body else None,
        )
