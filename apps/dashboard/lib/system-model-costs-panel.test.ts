import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("cost panel exposes distinct token, cost, validation, retry, and budget fields responsively", () => {
  const source = readFileSync(
    new URL("../components/system-model-costs-panel.tsx", import.meta.url),
    "utf8",
  );

  for (const label of (
    [
      "Input",
      "Cached input",
      "Cache write",
      "Uncached input",
      "Output",
      "Reasoning",
      "Total",
      "Reserved",
      "Reconciled",
      "Estimated",
      "Provider billed",
      "Validation errors",
      "Retry flags",
      "Remaining cost",
      "Remaining tokens",
      "Price card",
      "Model config",
      "Prompt version",
    ]
  )) {
    assert.match(source, new RegExp(`(?:>|label=")${label}(?:<|")`));
  }
  assert.match(source, /sm:grid-cols-2/);
  assert.match(source, /xl:grid-cols-7/);
  assert.match(source, /No model accounting has been persisted/);
  assert.match(source, /Reservation ledger/);
  assert.match(source, /released/i);
  assert.match(source, /Accounting blockers/);
  assert.match(source, /attempt\.tokens\.cachedInput/);
  assert.match(source, /attempt\.tokens\.cacheWrite/);
  assert.match(source, /attempt\.tokens\.uncachedInput/);
  assert.doesNotMatch(source, /raw|payload|reasoning_content|sanitized/i);
});
