# Investment Research OS V1 spec

## Outcome

Give one operator a private, auditable workspace for discovering and reviewing speculative equities mentioned in public discussions. System organizes evidence; it does not execute trades or present model output as fact.

## Product principles

1. **Evidence before opinion.** Every factual claim resolves to source passage, URL, publisher, timestamp, and retrieval time.
2. **Dimensions, not magic score.** Show evidence quality, catalyst strength, financial risk, valuation context, market confirmation, and information completeness separately.
3. **Human decision.** Models extract and challenge. Operator verifies sources and records decisions.
4. **Incremental research.** New evidence updates versioned thesis; system does not reread full history for every event.
5. **Approval-gated sources.** Provider stays disabled until access and processing scope are authorized.
6. **Content-level analysis.** Judge evidence quality, not Redditor identity or inferred traits.

## Users and scope

V1 has one authenticated operator and five surfaces:

- Discover
- Watchlist
- Ticker workspace
- Research queue
- System and model costs

No public signup, autonomous execution, options flow, minute-level ingestion, social posting, portfolio allocation, or candlestick prediction.

## Ticker workspace

Header shows price context, research status, thesis direction, evidence confidence, risk, and last review time.

Core panels:

1. **Thesis snapshot** — concise current view, bull case, bear case, unknowns.
2. **Evidence ledger** — claim, source passage, source class, verification status, conflict state.
3. **Discussion narratives** — recurring argument, mention count, momentum, independence estimate, evidence quality, disagreement. No author quality score.
4. **Research timeline** — filings, announcements, narrative changes, thesis revisions, decisions.
5. **Financial health** — cash, burn, runway, debt, revenue, share-count change, formulas, periods.
6. **Catalysts** — date/range, source, expected outcomes, confidence, thesis impact.
7. **Market context** — price, volume, sector-relative strength, volatility, drawdown, event markers.
8. **Research gaps** — missing primary sources, stale facts, contradictions, unresolved risks.
9. **Operator notes** — separate human view, decision, conditions, maximum experimental allocation.

## System shape

```text
Reddit (approval-gated)   SEC   issuer releases   market data
          |                |           |               |
          +----------------+-----------+---------------+
                                   |
                           Python collectors
                                   |
                        normalized source records
                                   |
                     deterministic filters and jobs
                                   |
                 evidence ledger + versioned ticker state
                                   |
                selected model inference (approval-gated)
                                   |
                         private Next.js dashboard
```

Planned runtime:

| Layer | V1 choice | Responsibility |
|---|---|---|
| Dashboard | Next.js App Router | Private research UI and server actions |
| Database | Supabase Postgres | Sources, claims, thesis versions, runs, notes |
| Files | Supabase Storage | Approved filing snapshots; Reddit raw cache only if approved |
| Jobs | Supabase Queues | Durable, idempotent work items |
| Schedule | Supabase Cron | Low-frequency collection and removal checks |
| Workers | Python | Collection, parsing, extraction, model routing |
| Models | Provider adapters | Cheap extraction first; frontier synthesis only on demand |
| Charts | Lightweight Charts or ECharts | Price, volume, events, narrative trend |

Supabase detail stays implementation-deferred. Before schema work: use private schemas for Reddit data, keep exposed tables RLS-protected, use explicit Data API grants, and never expose secret/service keys to frontend.

## Core data model

```text
companies -> securities -> market_snapshots
sources -> source_documents -> source_passages
claims -> claim_evidence -> claim_conflicts
narratives -> narrative_mentions
catalysts -> risks -> research_gaps
theses -> thesis_versions -> research_runs -> model_outputs
watchlists -> notes -> decisions -> positions
```

Required trace:

```text
thesis statement -> claim -> evidence passage -> original source
```

Forbidden trace:

```text
thesis statement -> model summary only
```

## Job contract

Initial jobs:

- `collect_reddit_posts` (disabled until approval)
- `collect_reddit_comments` (disabled until approval)
- `extract_ticker_candidates`
- `fetch_sec_filing`
- `extract_filing_facts`
- `update_market_snapshot`
- `cluster_narratives`
- `verify_claim`
- `generate_deep_review` (manual trigger)
- `check_reddit_removals` (disabled until approval)

Every job is idempotent, retry-bounded, prompt-versioned where relevant, linked to a research run, and records duration plus provider cost. Queue payloads contain IDs, not long source bodies.

## Model contract

Deterministic code handles collection, ticker syntax, deduplication, schedules, price math, and scoring. Model calls receive small evidence bundles and return structured data:

```json
{
  "claims": [],
  "bull_case": [],
  "bear_case": [],
  "risks": [],
  "catalysts": [],
  "unknowns": [],
  "unsupported_claims": [],
  "evidence_ids": []
}
```

Deep review triggers only after configurable evidence thresholds or manual request. No autonomous agent loops. No model sees Reddit content until approved processing and provider controls are documented.

## Current tracer acceptance criteria

- Fails clearly when required OAuth configuration is absent.
- Uses application-only OAuth and only the GET listing endpoint.
- Uses operator-specific User-Agent.
- Accepts one validated subreddit and 1-100 item limit.
- Omits body text by default.
- Omits author and account fields.
- Stops when rate-limit headers report exhausted quota.
- Makes no writes or automatic retries.
- Maps original permalinks into output.
- Tests execute without network or secrets.

## V1 delivery slices

1. **Approval tracer** — this repository state: docs, privacy posture, offline-tested read-only client.
2. **Evidence spine** — SEC source ingestion, source/passages/claims schema, manual ticker page.
3. **Approved discussion ingestion** — allowlist, queue, cache TTL, removal synchronization.
4. **Narrative extraction** — deterministic filters, structured model output, source-backed UI.
5. **Deep review** — manual frontier review, claim verifier, cost ledger, thesis versioning.

Each slice must pass targeted tests, source trace checks, and a real-runtime smoke test where credentials and approval permit.
