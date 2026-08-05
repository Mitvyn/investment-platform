import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("personal valuation provider caveats render with attention treatment", () => {
  const source = readFileSync(
    new URL("../app/research-runs/[runId]/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /Provider contract status/);
  assert.match(source, /Provider limitations/);
  assert.match(source, /source\.providerContractStatus/);
  assert.match(source, /source\.providerLimitationCodes/);
  assert.match(source, /border-warning\/35 bg-warning-muted\/10/);
});
