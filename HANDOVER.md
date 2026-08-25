# Handover: QUANT-004 local provider-fetch path

Originally isolated worktree. Integrated into `development` as `fcce828`;
kept as implementation handover for the provider-fetch slice.

```text
source worktree: /Users/mwong/Personal/investment-platform-quant-provider
source branch:   feature/quant-provider-dataset
integrated commit: fcce828 on development
```

## Scope delivered

The local implementation path end to end:

```text
selected canonical security
  -> server-derived ticker (loadSecurityDirectory(), never a browser value)
  -> explicit historical window (start date, as-of cutoff)
  -> approved yfinance transport (YFinanceHistoryTransport / LiveQuantSource)
  -> validated PointInTimeDataset
  -> existing Quant workspace storage (FileQuantWorkspaceStore)
  -> existing Quant analysis UI (QuantPanel)
```

No second dataset contract was introduced and no Quant core code was
rewritten. The provider fetch is reshaped into the exact same
`quant_local_dataset.v1` document a hand-written file import must satisfy, and
persisted through the exact same store, so it inherits restart durability,
tamper re-validation, and result invalidation for free.

## The one architectural discovery that shaped this

`workers/quant_workspace` is provider-neutral by construction, and
`tests/test_quant_workspace_isolation.py` enforces that with an AST import
scan: nothing in that package may import `workers.quant_sources`, yfinance, a
network client, or another bounded context. My first draft put the fetch glue
inside `workers/quant_workspace`, which broke that test immediately. The fix
was to move the glue into `workers/quant_sources/workspace_bridge.py` instead
— that package is not isolated, and its own allowed-import list explicitly
permits it to import `workers.quant_workspace` (never the reverse). This is
why `DesktopQuantService` in `workers/quant_workspace/service.py` was left
untouched except for one rename (`_dataset_receipt` -> `dataset_receipt`, made
public so the bridge could reuse the sanitizing shape function instead of
duplicating it), and why the provider fetch is a second, sibling service
(`ProviderQuantWorkspaceBridge`) rather than a new method on
`DesktopQuantService`.

## Changed and new files

| File | Change |
|---|---|
| `workers/quant_sources/live.py` | `LiveQuantSource.acquire` gained an optional `currency` (omitted: trusts the provider's own, already ISO-4217-validated currency instead of assuming USD; supplied: still enforces the match exactly as before). Internals factored into `_acquire`. New `acquire_with_rows`/`LiveAcquisition` expose the exact provider-declared rows behind a receipt, because the receipt's own values are already Decimal-normalised and cannot be replayed into a document without breaking its content hash. |
| `workers/quant_sources/workspace_bridge.py` | new. `fetch_provider_dataset_document`, `fetch_provider_dataset`, and `ProviderQuantWorkspaceBridge`. The one module that imports both `workers.quant_sources.live` and `workers.quant_workspace.*`. |
| `workers/quant_workspace/service.py` | one rename only: `_dataset_receipt` -> `dataset_receipt` (public). No new import, no isolation-boundary change. |
| `workers/desktop/control.py` | `DesktopControlServer` gained an optional `quant_provider_bridge` constructor arg and a `/v1/quant/dataset/fetch` POST route, separate from the existing `quant_service`/`/v1/quant/dataset/import` route. |
| `workers/desktop/__main__.py` | wires `ProviderQuantWorkspaceBridge` with a real `YFinanceHistoryTransport(YFinanceSettings(), window_semantics=yfinance_end_exclusive_policy())`. This is the only place a live network call becomes reachable, and only when an operator actually submits the fetch form. |
| `packages/types/quant-workspace.ts` | added five reviewed error codes: `fetch_provider_blocked`, `fetch_provider_rejected`, `fetch_provider_unavailable`, `fetch_ticker_invalid`, `fetch_window_invalid`. |
| `apps/dashboard/lib/quant-desktop.ts` | new `fetchQuantDataset` client function, mirroring `importQuantDataset`. |
| `apps/dashboard/lib/quant-workspace.ts` | plain-language messages for the five new codes; the "no dataset" headline now mentions fetch as well as import. |
| `apps/dashboard/app/quant-actions.ts` | new `fetchQuantDatasetAction`. `authorizedRequest` now also returns the matched security-directory entry, so the ticker is derived server-side and never taken from the form. |
| `apps/dashboard/components/quant-panel.tsx` | a "Fetch from provider" form (start date, as-of cutoff) beside the existing import form. |
| `packages/types/quant-workspace.test.ts`, `apps/dashboard/lib/quant-desktop.test.ts`, `tests/test_quant_source_workspace_bridge.py`, `tests/test_desktop_quant.py` | new/extended tests, see Validation. |

Nothing in `workers/research_committee`, `workers/primary_sources`,
`workers/portfolio`, `workers/moomoo_mcp`, Research, committee, valuation, or
account-change code was touched. `apps/dashboard/desktop/preload.ts` is
unchanged.

## Currency handling

Requirement was: never assume or infer currency, use the provider's declared
value, validate it explicitly, reject a mismatch. Two layers already existed
and are reused rather than reimplemented:

- `HistoryPayload.__post_init__` (existing, unchanged) already refuses any
  currency that is not an upper-case three-letter ISO 4217 code.
- `LiveQuantSource.acquire`'s new optional `currency` lets a caller with an
  independent expectation still get a hard mismatch check (unchanged
  behaviour for every existing caller, which all pass one explicitly). The
  new fetch path has no independent currency of its own — Quant's boundary
  rule is that only `security_id` crosses in, not a security's listing
  currency — so it passes none and the already-validated provider currency is
  used as-is.

## RED then GREEN

- `tests/test_quant_source_workspace_bridge.py` did not exist before this
  slice: run against the pre-fix tree it fails with
  `ModuleNotFoundError: No module named 'workers.quant_sources.workspace_bridge'`.
- The isolation boundary itself was caught the same way, live: an earlier
  draft that put the bridge inside `workers/quant_workspace` failed
  `test_quant_imports_only_the_standard_library_and_its_own_code` with
  `AssertionError: ... imports 'workers.quant_sources.live', which is outside
  the Quant boundary` — moving the module fixed it, and that test is now
  green with the final layout.
- GREEN: see Validation below.

## Validation

Run from this worktree's root unless noted.

| Command | Result |
|---|---|
| `PYTHONPATH=src:. python3 -m unittest tests.test_quant_source_workspace_bridge` | 21 OK |
| `PYTHONPATH=src:. python3 -m unittest tests.test_quant_source_transports` | 87 OK |
| `PYTHONPATH=src:. python3 -m unittest tests.test_desktop_quant` | 29 OK |
| `PYTHONPATH=src:. python3 -m unittest tests.test_quant_workspace_isolation` | 4 OK |
| `PYTHONPATH=src:. python3 -m unittest discover -s tests` | 1884 run, 3 errors, all pre-existing and environmental |
| `node --test --experimental-strip-types packages/types/quant-workspace.test.ts` | 12 OK |
| `node --test --experimental-strip-types "packages/types/*.test.ts"` | 127 pass |
| `node --test --experimental-strip-types apps/dashboard/lib/quant-desktop.test.ts` | 19 OK |
| `node --test --experimental-strip-types "apps/dashboard/app/**/*.test.ts" "apps/dashboard/lib/*.test.ts"` (from repo root) | 335 pass |
| `./node_modules/.bin/tsc --noEmit` (in `apps/dashboard`) | clean |
| `next build --webpack` (in `apps/dashboard`) | compiled, 5 routes |
| `python3 -m compileall -q src tests workers` | clean |
| `git diff --check` | clean |

The three full-suite errors are the same pre-existing environmental ones
already recorded in IRO-072's handover: two `curl_cffi` loader errors
(`test_primary_source_acquisition`, `test_primary_source_cli`) and the missing
operator-local `data/primary-source-captures/rxrx-2026-05-06-v3.zip`.

`node_modules` and `apps/dashboard/node_modules` were temporarily symlinked
from the main worktree to run typecheck/build, then removed, along with the
generated `apps/dashboard/.next`.

### Not validated

- Any real network call to Yahoo Finance. Every test uses an injected fake
  transport. The production wiring in `workers/desktop/__main__.py` is real,
  but exercising it requires an operator running the packaged desktop worker
  and submitting the fetch form; that is exactly the boundary QUANT-004 asks
  to keep operator-gated.
- Packaged desktop build (PyInstaller/pnpm frozen install). Nothing in this
  slice changes what the desktop worker imports at the module level beyond
  the new provider bridge and transport, both pure-Python, so no packaging
  change should be needed, but it was not built and run here.

## Known limits

- The fetch route persists a fresh dataset unconditionally; it does not
  compare against whatever dataset is already active before overwriting, the
  same as the existing file-import route. Requirement 4's "import replaces
  active dataset atomically" is satisfied by `FileQuantWorkspaceStore`'s
  existing same-directory atomic write.
- `ProviderQuantWorkspaceBridge` is unauthenticated at its own layer; it
  trusts the desktop control server's existing bearer-token check exactly
  like every other quant route.
- Moomoo historical acquisition is untouched and still blocked by
  `MOOMOO_HISTORY_BLOCKER` in `workers/quant_sources/live.py`. This slice does
  not implement or guess it.
- yfinance's actual live response shape (currency field presence, session
  boundary behaviour under a real network call) was previously verified only
  documentarily (`yfinance_end_exclusive_policy`, dated 2026-08-17). This
  slice adds no new live evidence; it only wires the already-approved
  transport through to the workspace.

## Exact next step

An operator runs the packaged desktop worker, selects a security with a
canonical ticker, and submits the fetch form once to produce the first real
`yahoo_finance_via_yfinance` dataset receipt. That is the remaining
operator-gated proof; nothing further needs to be coded to reach it.

## Prohibited interactions

None occurred. No hosted Supabase, migration, provider, model, Moomoo, Reddit,
or live network call; no MCP, portfolio, holdings, Research, committee,
valuation, trade, order, or account-change path was read or written. The main
`development` worktree was not written to.
