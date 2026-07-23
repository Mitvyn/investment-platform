import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Research Run workspace loads and displays canonical committee memo", () => {
  const source = readFileSync(
    new URL("../app/research-runs/[runId]/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /loadCommitteeMemo/);
  assert.match(source, /projectResearchRunAuditWorkspace/);
  assert.match(source, /<CommitteeMemoPanel presentation={memoPresentation} \/>/);
});
