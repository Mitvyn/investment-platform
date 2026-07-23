# Security onboarding worker

This fixed-purpose worker bridges authenticated dashboard registration jobs to
the existing SEC security registry and personal-use yfinance market intake. It
does not execute arbitrary commands, Research Runs, model calls, or portfolio
actions.

## Runtime

MVP runs as one operator-managed local process:

```bash
set -a
source .env.local
set +a
python3 -m workers.security_onboarding run
```

Use `run-once` for one queue check during an authorized smoke test. The process
requires:

- `IROS_WORKER_ID`: non-secret stable worker label;
- `IROS_SUPABASE_URL`: shared project URL;
- `IROS_SUPABASE_SECRET_KEY`: server-only Supabase secret key;
- `SEC_USER_AGENT`: SEC-compliant contact User-Agent.

The dashboard never receives these values. Do not use the browser publishable
key for worker persistence.

## Reliability boundary

- Jobs use five-minute leases and at most two attempts per request generation.
- Retryable failures requeue after five seconds.
- Terminal failures remain auditable; resubmission creates a new generation.
- Unexpected processing errors become bounded `worker/unexpected_failure`
  results.
- The dashboard pauses automatic polling after two minutes and asks for a
  manual reload; it does not relabel the persisted job.

No production daemon, scheduler, or health service is selected yet. A hosted
worker deployment is a later operational decision and must preserve this fixed
job contract, server-only credentials, lease recovery, and IROS-only access.
