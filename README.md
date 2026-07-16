# Investment Research OS

Private, evidence-first investment discussion organizer. Early prototype exists to support a Reddit Data API access request; it is not a trading bot, public product, or investment-advice service.

## Status

**Approval-gated.** This repository does not access Reddit unless its operator receives explicit approval and configures OAuth credentials. Current code implements one read-only tracer: fetch recent public post metadata from one configured subreddit and print JSON. It does not persist data or invoke an AI model.

Reddit's current policies require approval for API access and direct developers to Devvit first. This external app needs a private off-Reddit interface that combines selected discussions with SEC filings, issuer disclosures, and market data. See [copy-ready application answers](docs/reddit-application.md) and [data controls](docs/data-handling.md).

## Purpose

Investment Research OS aims to turn noisy public discussion into auditable research artifacts:

```text
approved sources -> deterministic filters -> claims -> evidence -> private ticker workspace
```

Every conclusion must link to evidence and its original source. Model output is analysis, never source-of-truth data. Full product boundary lives in [product spec](docs/product-spec.md).

## Current behavior

- OAuth application-only authentication with a GET-only client
- unique operator-supplied User-Agent
- one bounded `/r/{subreddit}/new` request, maximum 100 items
- no scraping, retries, polling loop, persistence, or write actions
- body text omitted unless `--include-body` is supplied
- author/account fields omitted from normalized output
- rate-limit headers observed; collection stops when quota is exhausted
- typed configuration and API failures without secret logging
- injected HTTP transport for offline tests

## Local setup

Requires Python 3.11+ and approved Reddit API credentials.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
cp .env.example .env
```

Edit `.env`, then load it into shell:

```bash
set -a
source .env
set +a
iros fetch-new --subreddit stocks --limit 5
```

Keep `REDDIT_API_APPROVED=false` until Reddit grants explicit approval. Set it
to `true` only after approved credentials and scope are confirmed.

Include post body only when approved processing needs it:

```bash
iros fetch-new --subreddit stocks --limit 5 --include-body
```

Never commit `.env` or command output containing Reddit content.

## Validation

Tests use local fakes and make no network calls:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

## Repository map

```text
src/investment_research_os/  read-only OAuth client and CLI
tests/                       offline contract tests
docs/product-spec.md         V1 product and architecture
docs/reddit-application.md   proposed form answers
docs/data-handling.md        collection and retention controls
PRIVACY.md                   public privacy notice
```

## Compliance boundary

- No API access before explicit Reddit approval.
- No automated posting, commenting, voting, messaging, or moderation.
- No Reddit scraping or access-control circumvention.
- No public redistribution or sale of Reddit data.
- No model training on Reddit content.
- No user profiling, sensitive-trait inference, or identity matching.
- AI inference remains disabled until approved scope and provider controls are confirmed.
- Removed/deleted content must be purged from local cache and derived records.

See Reddit's [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy), [Developer Platform and Data API guidance](https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data), and [Data API Terms](https://redditinc.com/policies/data-api-terms).

## Disclaimer

Research output is informational, may be wrong, and is not financial advice. Operator remains responsible for source verification and investment decisions.

## License

[MIT](LICENSE) applies to source code. It grants no rights to Reddit content, third-party content, trademarks, or data.
