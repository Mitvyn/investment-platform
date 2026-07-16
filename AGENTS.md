# Repository guidance

## Product boundary

- Keep Reddit integration read-only. Never add posting, commenting, voting, messaging, moderation, or user-interaction actions without an explicit scope change and Reddit approval.
- Do not call Reddit before API approval. Tests must use local fakes.
- Do not scrape Reddit or bypass access controls, rate limits, labels, removals, or OAuth.
- Do not train models on Reddit content or build Reddit-user profiles. Never infer sensitive user traits.
- Keep model inference disabled until Reddit approves the disclosed processing scope and the selected provider's retention/training terms are verified.
- Preserve source attribution and original Reddit permalinks in every derived research artifact.
- Do not retain Reddit usernames or account IDs in V1 normalized records.
- Keep any future raw Reddit text cache at or below 48 hours unless Reddit explicitly approves another period.

## Engineering

- Python 3.11+ for collectors and workers. Prefer standard library until a dependency has clear value.
- Keep network transport injectable. Never make live network calls in tests.
- Secrets belong in environment variables. Never commit `.env`, tokens, credentials, or captured Reddit content.
- Add focused `unittest` coverage for request shape, response mapping, validation, and failures.

## Validation

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
git diff --check
```
