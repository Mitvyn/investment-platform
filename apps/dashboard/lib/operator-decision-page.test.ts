import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Research Run workspace loads and displays owner-scoped operator decisions", () => {
  const source = readFileSync(
    new URL("../app/research-runs/[runId]/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /loadResearchRunFlow/);
  assert.match(
    source,
    /<OperatorDecisionPanel presentation={operatorDecisionPresentation} \/>/,
  );

  const flowSource = readFileSync(
    new URL("./research-run-flow.ts", import.meta.url),
    "utf8",
  );
  assert.match(flowSource, /loadOperatorDecisions/);
  assert.match(flowSource, /projectResearchRunAuditWorkspace/);
});
