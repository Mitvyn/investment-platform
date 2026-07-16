from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Sequence

from .config import ConfigError, RedditSettings
from .reddit import RedditApiError, RedditClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iros",
        description="Approval-gated, read-only Reddit API tracer.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    fetch_new = commands.add_parser(
        "fetch-new",
        help="Fetch recent public posts from one subreddit.",
    )
    fetch_new.add_argument("--subreddit", required=True)
    fetch_new.add_argument("--limit", type=int, default=10)
    fetch_new.add_argument(
        "--include-body",
        action="store_true",
        help="Include post body text in stdout output.",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        settings = RedditSettings.from_env()
        client = RedditClient(settings)
        posts = client.fetch_new_posts(
            args.subreddit,
            limit=args.limit,
            include_body=args.include_body,
        )
    except (ConfigError, RedditApiError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    json.dump([asdict(post) for post in posts], sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def main() -> None:
    raise SystemExit(run())
