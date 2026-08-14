import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Research Run workspace loads and displays canonical committee memo", () => {
  const source = readFileSync(
    new URL("../app/research-runs/[runId]/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /loadResearchRunFlow/);
  assert.match(source, /<CommitteeMemoPanel presentation={memoPresentation} \/>/);

  const flowSource = readFileSync(
    new URL("./research-run-flow.ts", import.meta.url),
    "utf8",
  );
  assert.match(flowSource, /loadCommitteeMemo/);
  assert.match(flowSource, /projectResearchRunAuditWorkspace/);
});
