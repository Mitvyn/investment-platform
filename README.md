# Investment Research OS

Private, evidence-first investment discussion organizer. Early prototype exists to support a Reddit Data API access request; it is not a trading bot, public product, or investment-advice service.

## Status

**Phase 1 complete; Phase 2 implementation in progress.** Reddit remains
disabled unless its operator receives explicit approval and configures OAuth
credentials. The RXRX workspace now has SEC evidence plus local issuer,
financial, catalyst, risk, Watchlist, source-health, and gated market-context
paths. No model is called.

Reddit's current policies require approval for API access and direct developers to Devvit first. This external app needs a private off-Reddit interface that combines selected discussions with SEC filings, issuer disclosures, and market data. Copy-ready application answers and data controls are maintained in the local canonical project documentation.

## Purpose

Investment Research OS aims to turn noisy public discussion into auditable research artifacts:

```text
approved sources -> deterministic filters -> claims -> evidence -> private ticker workspace
```

Every conclusion must link to evidence and its original source. Model output is analysis, never source-of-truth data. The full product boundary lives at `docs/01-Product/PRD - Investment Research OS v1.md`.

## Planned model strategy

- `deepseek-v4-flash`: default general model for classification, extraction,
  summaries, narrative clustering, gaps, and preliminary memos.
- `gpt-5.6-sol`: gated reasoning model for cross-source synthesis,
  contradictions, complex financial/scientific analysis, thesis changes, and
  investment-committee review.
- deterministic code: collection, deduplication, price/financial math,
  citations, routing, token accounting, and budgets.

Sol never reads raw corpus. It receives compact evidence packs after Flash and
primary-source verification. Every model call records input, cached input,
output, reasoning and total tokens; price-card version; cost; prompt version;
and evidence-bundle hash.

See `docs/02-Engineering/model-routing-and-costs.md`.

## Target repository shape

Product name remains Investment Research OS. Target repository name is
`stock-research-os`.

```text
apps/dashboard
apps/api
workers/{reddit,sec,news,market,llm,embeddings}
packages/{shared,prompts,models,types}
database/{migrations,schema}
docs
```

Current `src/investment_research_os` remains narrow Reddit approval tracer.
Target package tree appears only as implementation reaches each boundary.

V1 uses an existing shared personal Supabase project. Investment Research OS
tables, views, functions, queues, Cron jobs, and types use `iros_`; Storage
buckets use `iros-`. Existing Wellness objects retain `well_` and remain
outside this project's migrations and runtime queries.

## Current behavior

Primary-source evidence tracer:

- fetches one exact SEC filing through injectable transport;
- extracts one exact passage using deterministic text matching;
- records stable research-run, source, document, passage, claim, and evidence
  IDs;
- persists with idempotent PostgREST inserts into explicit `iros_` tables;
- exposes authenticated read-only trace through
  `iros_v_claim_evidence_trace`;
- renders only the authenticated hosted Supabase trace in Next.js;
- never gives dashboard a backend secret-key path.

Phase 2 ticker context:

- fetches Recursion's official Q1 2026 issuer release through injectable
  transport;
- requires exact unique passages before emitting financial, catalyst, or risk
  records;
- calculates runway and cash-flow changes with formulas and source periods;
- provides an injectable Twelve Data quote adapter that fails before network
  when no key is configured;
- reads issuer, risk, market, and operator-managed Watchlist data through
  authenticated Supabase paths;
- keeps provider and backend secret credentials out of the dashboard.

Reddit approval tracer:

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

Requires Python 3.11+. Dashboard requires Node.js and pnpm.

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

### Phase 1 RXRX tracer

Install dashboard dependencies:

```bash
pnpm install
```

Start the authenticated dashboard:

```bash
pnpm dashboard:dev
```

Live SEC ingestion is a deliberate privileged operator action. Pre-provision
the dashboard operator in Supabase Auth, then configure
`SEC_USER_AGENT`, `IROS_OPERATOR_ID`, `IROS_SUPABASE_URL`, and
`IROS_SUPABASE_SECRET_KEY`, review migration first, then run:

```bash
python3 -m workers.sec ingest-rxrx-q2-2025
```

Worker stores one supported RXRX claim from SEC accession
`0001601830-25-000127`. Reruns reuse stable IDs and ignore duplicate inserts.
After two ingestion runs, verify each deterministic ID resolves to exactly one
matching hosted row:

```bash
python3 -m workers.sec verify-rxrx-q2-2025
```

The hosted migration is applied and linked migration history is current. Live
ingestion ran twice on 2026-07-16. Both runs resolved to research run
`f8e80094-84b6-5d2b-a61f-e29dac281dbe`; hosted verification found exactly one
matching row in every evidence table and preserved the first retrieval time
and filing content hash.

### Phase 2 RXRX context

The issuer collector uses no personal contact identity and reads only the
canonical Recursion investor-relations release:

```bash
python3 -m workers.issuer ingest-rxrx-q1-2026
python3 -m workers.issuer verify-rxrx-q1-2026
```

These commands require `IROS_OPERATOR_ID`, `IROS_SUPABASE_URL`, and
`IROS_SUPABASE_SECRET_KEY`. Hosted database operations are operator-owned;
do not run ingestion or verification without explicit authorization.

Market ingestion additionally requires `TWELVE_DATA_API_KEY` from a plan whose
license permits authenticated dashboard display:

```bash
python3 -m workers.market
```

No live market request has been made. The dashboard shows a gated empty state
until a licensed snapshot exists.

Phase 2 migrations:

- `20260717021804_iros_phase2_ticker_context.sql` was applied on 2026-07-17;
- operator reports `20260717023818_iros_phase2_watchlist_risks.sql` applied on
  2026-07-17; hosted verification remains pending.

The operator applies migrations. Agents must not push, query, ingest, run
advisors, or database-smoke the hosted project without explicit permission in
the current request.

`supabase/migrations` is a relative symlink to
`../../wellness-time/supabase/migrations`. Power Up owns canonical migration
history for the shared Supabase project. Investment Research OS changes remain
isolated through the `iros_` object prefix.

Authenticated dashboard reads require `IROS_SUPABASE_URL`,
`IROS_SUPABASE_PUBLISHABLE_KEY`, and a pre-provisioned Supabase Auth operator.
Set `IROS_SITE_URL` to the deployed origin. The login form requests a
passwordless link but cannot create new users. Supabase SSR owns the session
cookies and the dashboard redirects unauthenticated requests to `/login`.

## Validation

Tests use local fakes and make no network calls:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests workers
CI=true pnpm dashboard:typecheck
CI=true pnpm dashboard:build
git diff --check
```

## Repository map

Canonical project documentation is maintained in MeowingVault and exposed
locally through the ignored `docs` symlink. Opening `docs` shows the project
root directly:

- `docs/01-Product/PRD - Investment Research OS v1.md`
- `docs/02-Engineering/architecture-overview.md`
- `docs/02-Engineering/model-routing-and-costs.md`
- `docs/02-Engineering/prompting-and-evaluations.md`
- `docs/02-Engineering/database-and-data-contracts.md`
- `docs/02-Engineering/reddit-api-integration.md`
- `docs/02-Engineering/reddit-data-api-application.md`
- `docs/02-Engineering/data-handling.md`
- `docs/03-Development/roadmap.md`
- `docs/03-Development/project-handoff.md`
- [Privacy notice](PRIVACY.md)

The vault-backed documentation is intentionally not committed to this public
repository.

Current code:

```text
apps/dashboard/                authenticated evidence-ledger Ticker Workspace
packages/types/                evidence and ticker-context contracts
supabase/migrations/           `iros_` evidence, context, RLS, Watchlist
workers/sec/                   injectable SEC collector and persistence
workers/issuer/                official release, financial, catalyst, risk path
workers/market/                gated Twelve Data quote adapter
src/investment_research_os/  read-only OAuth client and CLI
tests/                         offline contract and migration tests
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
