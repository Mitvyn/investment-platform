import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Research Run workspace loads and displays deterministic readiness and thesis history", () => {
  const source = readFileSync(
    new URL("../app/research-runs/[runId]/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /loadResearchRunFlow/);
  assert.match(source, /<ReadinessThesisPanel presentation={readinessPresentation} \/>/);

  const flowSource = readFileSync(
    new URL("./research-run-flow.ts", import.meta.url),
    "utf8",
  );
  assert.match(flowSource, /loadReadinessThesis/);
  assert.match(flowSource, /projectResearchRunAuditWorkspace/);
});

test("missing current memo keeps an existing ownership thesis chain visible", () => {
  const source = readFileSync(
    new URL("../app/research-runs/[runId]/page.tsx", import.meta.url),
    "utf8",
  );

  const flowSource = readFileSync(
    new URL("./research-run-flow.ts", import.meta.url),
    "utf8",
  );
  assert.match(flowSource, /loadExistingThesisChain/);
  assert.doesNotMatch(
    source,
    /committeeMemo === null\s*\? \{ readiness: null, creation: null, thesis: null, chain: null \}/,
  );
});
