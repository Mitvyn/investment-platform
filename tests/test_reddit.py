from __future__ import annotations

import unittest
from typing import Any, Mapping

from investment_research_os import RedditApiError, RedditClient, RedditSettings
from investment_research_os.reddit import JsonResponse


class FakeTransport:
    def __init__(self, responses: list[JsonResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        form: Mapping[str, str] | None = None,
    ) -> JsonResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "form": dict(form) if form is not None else None,
            }
        )
        return self.responses.pop(0)


def settings() -> RedditSettings:
    return RedditSettings(
        client_id="client-id",
        client_secret="client-secret",
        user_agent="macos:investment-research-os:v0.1.0 (by /u/example)",
    )


def token_response() -> JsonResponse:
    return JsonResponse(
        payload={"access_token": "access-token", "expires_in": 3600},
        status=200,
        headers={},
    )


def listing_response() -> JsonResponse:
    return JsonResponse(
        payload={
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "id": "abc123",
                            "subreddit": "stocks",
                            "title": "Example discussion",
                            "author": "example_author",
                            "permalink": "/r/stocks/comments/abc123/example/",
                            "created_utc": 1_700_000_000,
                            "score": 42,
                            "num_comments": 7,
                            "selftext": "Example body",
                        },
                    }
                ]
            }
        },
        status=200,
        headers={"x-ratelimit-remaining": "99"},
    )


class RedditClientTests(unittest.TestCase):
    def test_fetches_new_posts_with_read_only_oauth(self) -> None:
        transport = FakeTransport([token_response(), listing_response()])
        client = RedditClient(settings(), transport=transport)

        posts = client.fetch_new_posts("stocks", limit=5)

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].id, "abc123")
        self.assertEqual(posts[0].body, None)
        self.assertEqual(
            posts[0].permalink,
            "https://www.reddit.com/r/stocks/comments/abc123/example/",
        )

        token_request, listing_request = transport.requests
        self.assertEqual(token_request["method"], "POST")
        self.assertEqual(
            token_request["form"],
            {"grant_type": "client_credentials"},
        )
        self.assertTrue(token_request["headers"]["Authorization"].startswith("Basic "))
        self.assertEqual(listing_request["method"], "GET")
        self.assertIn("/r/stocks/new?", listing_request["url"])
        self.assertIn("limit=5", listing_request["url"])
        self.assertEqual(
            listing_request["headers"]["Authorization"],
            "Bearer access-token",
        )
        self.assertNotIn("author", posts[0].__dataclass_fields__)
        self.assertEqual(client.last_rate_limit.remaining, 99)

    def test_includes_body_only_when_requested(self) -> None:
        transport = FakeTransport([token_response(), listing_response()])
        client = RedditClient(settings(), transport=transport)

        posts = client.fetch_new_posts("stocks", include_body=True)

        self.assertEqual(posts[0].body, "Example body")

    def test_reuses_unexpired_access_token(self) -> None:
        transport = FakeTransport(
            [token_response(), listing_response(), listing_response()]
        )
        client = RedditClient(settings(), transport=transport)

        client.fetch_new_posts("stocks")
        client.fetch_new_posts("investing")

        token_requests = [
            request for request in transport.requests if request["method"] == "POST"
        ]
        self.assertEqual(len(token_requests), 1)

    def test_rejects_invalid_subreddit_before_network_call(self) -> None:
        transport = FakeTransport([])
        client = RedditClient(settings(), transport=transport)

        with self.assertRaisesRegex(ValueError, "subreddit"):
            client.fetch_new_posts("../private")

        self.assertEqual(transport.requests, [])

    def test_rejects_out_of_range_limit_before_network_call(self) -> None:
        transport = FakeTransport([])
        client = RedditClient(settings(), transport=transport)

        with self.assertRaisesRegex(ValueError, "limit"):
            client.fetch_new_posts("stocks", limit=101)

        self.assertEqual(transport.requests, [])

    def test_rejects_malformed_listing(self) -> None:
        transport = FakeTransport(
            [
                token_response(),
                JsonResponse(payload={"unexpected": True}, status=200, headers={}),
            ]
        )
        client = RedditClient(settings(), transport=transport)

        with self.assertRaisesRegex(RedditApiError, "listing response"):
            client.fetch_new_posts("stocks")

    def test_stops_when_rate_limit_is_exhausted(self) -> None:
        exhausted = listing_response()
        exhausted = JsonResponse(
            payload=exhausted.payload,
            status=exhausted.status,
            headers={
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": "120",
            },
        )
        transport = FakeTransport([token_response(), exhausted])
        client = RedditClient(settings(), transport=transport)

        with self.assertRaisesRegex(RedditApiError, "120 seconds"):
            client.fetch_new_posts("stocks")


if __name__ == "__main__":
    unittest.main()
