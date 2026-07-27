# Repository guidance

## Product boundary

- Reddit Data API request was rejected on 2026-07-25. Keep Reddit integration
  retired from runtime and active roadmap.
- Do not call Reddit APIs, scrape Reddit, automate Reddit-targeted web search,
  or use search providers as an access workaround.
- Do not ingest, store, score, summarize, cite, or send Reddit content,
  metadata, snippets, links, sentiment, or identities to models.
- General operator-initiated web search may incidentally surface an untrusted
  discovery lead. Only its independently retrieved original primary source may
  enter the evidence workflow.
- Reject Reddit and other discovery-only URLs at evidence-bundle boundaries.
- Reopening Reddit access requires separately approved product, policy, legal,
  privacy, and implementation scope.

## Engineering

- Python 3.11+ for collectors and workers. Prefer standard library until a dependency has clear value.
- Keep network transport injectable. Never make live network calls in tests.
- Secrets belong in environment variables. Never commit `.env`, tokens, credentials, or captured Reddit content.
- Add focused `unittest` coverage for request shape, response mapping, validation, and failures.
- Hosted database is shared personal Supabase project. Prefix every Investment Research OS database object with `iros_`.
- Existing Wellness objects use `well_`. Never alter or reference them without explicit cross-project scope.
- `supabase/migrations` is a local symlink to the canonical shared migration
  folder at `../../wellness-time/supabase/migrations`.
- Create new migrations through the Investment Research OS path, but edit only
  `iros_` migration files unless explicit cross-project scope is open.
- Never replace the migration symlink with a copied directory.
- Do not create cross-project foreign keys. Validate migrations against unrelated prefixes before applying.
- The operator applies migrations and owns hosted database operations. Do not
  push migrations, query hosted data, ingest hosted records, run database
  advisors, or perform authenticated database smoke tests unless the operator
  explicitly authorizes that database interaction in the current request.
- Use lowercase `snake_case` identifiers. Never issue schema-wide grants in shared `public`; grant explicit `iros_` objects only.
- Enable RLS on exposed `iros_` tables with operator ownership predicates.

## Documentation

- `docs` is an ignored local symlink to the canonical MeowingVault project root.
- Before substantive work, read `docs/AGENTS.md`, `docs/context.md`, and `docs/03-Development/project-handoff.md`.
- Keep canonical project documentation current in the same work session as code, schema, workflow, or product-boundary changes.
- Do not replace `docs` with a committed directory or introduce another project-name layer beneath it.
- Never store secrets, credentials, captured Reddit content, or personal financial data in documentation.

## Validation

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests workers
pnpm dashboard:typecheck
pnpm dashboard:build
git diff --check
```
