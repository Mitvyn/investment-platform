import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Research Run page loads and renders owner-scoped model accounting", () => {
  const source = readFileSync(
    new URL("../app/research-runs/[runId]/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /loadModelCosts\(run\.operator_id, run\.id\)/);
  assert.match(source, /presentModelCostWorkspace\(modelCosts\)/);
  assert.match(
    source,
    /<SystemModelCostsPanel presentation=\{modelCostPresentation\} \/>/,
  );
});
