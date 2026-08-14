import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Research flow and audit route share one artifact loader", () => {
  const loader = readFileSync(
    new URL("./research-run-flow.ts", import.meta.url),
    "utf8",
  );
  const tickerPage = readFileSync(
    new URL("../app/page.tsx", import.meta.url),
    "utf8",
  );
  const auditPage = readFileSync(
    new URL("../app/research-runs/[runId]/page.tsx", import.meta.url),
    "utf8",
  );

  for (const dependency of [
    "loadEvidenceBundle",
    "loadValuationSnapshot",
    "loadGraderExecutions",
    "loadGraderCommittee",
    "loadCommitteeMemo",
    "loadReadinessThesis",
    "loadOperatorDecisions",
    "projectResearchRunAuditWorkspace",
  ]) {
    assert.match(loader, new RegExp(`\\b${dependency}\\b`));
  }
  assert.match(tickerPage, /loadResearchRunFlow/);
  assert.match(auditPage, /loadResearchRunFlow/);
});

test("Research artifact stages render inline when persisted flow is available", () => {
  const page = readFileSync(
    new URL("../app/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(page, /activeStage === "opinions"/);
  assert.match(page, /<GraderExecutionPanel/);
  assert.match(page, /activeStage === "committee"/);
  assert.match(page, /<GraderCommitteePanel/);
  assert.match(page, /<CommitteeMemoPanel/);
  assert.match(page, /activeStage === "thesis"/);
  assert.match(page, /<ReadinessThesisPanel/);
  assert.match(page, /<OperatorDecisionPanel/);
  assert.match(page, /researchFlow === null/);
});
