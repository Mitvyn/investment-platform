# Reddit data handling plan

Status: proposed controls for API review. No live Reddit collection starts before written approval.

## Scope

| Area | V1 rule |
|---|---|
| Access | Approved OAuth only; public posts and comments from explicit subreddit allowlist |
| Actions | Read-only; no posts, comments, votes, messages, moderation, or user interaction |
| Frequency | Scheduled low-frequency collection within assigned limits; no real-time firehose |
| Users | One private operator |
| Distribution | No public feed, data export, resale, or third-party user access |
| Identity | Preserve attribution links; no off-platform matching or Redditor profiles |
| AI training | Prohibited |
| AI inference | Disabled until Reddit and processor conditions permit disclosed use |

## Minimum fields

Planned post/comment records use only fields needed for organization and traceability:

- Reddit object ID and parent ID;
- subreddit;
- title and text, when approved analysis needs text;
- creation time;
- score and comment count as point-in-time context;
- canonical permalink;
- retrieval time and deletion-check time.

V1 will not retain usernames or account IDs and will not collect private account data, private messages, vote history, subscribed communities, saved items, or off-platform identifiers. Canonical permalinks preserve source context.

## Processing

1. Collector fetches approved public objects through OAuth.
2. Deterministic code validates scope, removes duplicates, and extracts candidate ticker strings.
3. Evidence records retain original permalinks and separate source text from derived claims.
4. If separately approved, selected text may receive one-time classification or summarization. Provider must not train on inputs and must meet documented retention controls.
5. Human reviews source passages before promoting a claim into a ticker thesis.

AI output cannot create a citation. It may reference only stored evidence IDs that resolve to original source URLs.

## Storage and removal

- Current tracer writes nothing to a database.
- Planned raw text cache limit: 48 hours unless Reddit explicitly approves another period.
- Keep secrets in server-only environment variables.
- Encrypt hosted storage and restrict it to one authenticated operator.
- Do not expose raw Reddit tables through a public Data API.
- Run removal checks against saved object IDs and delete cached text plus dependent derived records when content is removed or deleted.
- On API revocation or project shutdown, stop collection and delete cached Reddit content and its derivatives.

## Supabase boundary for later V1

If Supabase is added, Reddit content belongs in a private, non-exposed schema. Dashboard access goes through narrow server-side functions. Any exposed table must have RLS plus owner-specific policies; service-role or secret keys must never reach the browser. Queue payloads carry object IDs, not full Reddit text.

Supabase Queues and Cron are candidates for durable jobs and schedules, not requirements for this approval tracer.

## Logging and incidents

Allowed logs: request ID, endpoint class, status, duration, rate-limit headers, object count, and error code.

Forbidden logs: OAuth credentials, access tokens, full post/comment bodies, usernames not needed for incident diagnosis, model prompts containing Reddit content, or sensitive inferred attributes.

If data is exposed, stop affected jobs, revoke credentials, identify affected records, delete exposed copies, and follow Reddit/provider notification requirements.
