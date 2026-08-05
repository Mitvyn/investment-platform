import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { ResearchRun } from "../../../packages/types/research-run.ts";
import type { ResearchRunHistory } from "./research-run-history-loader.ts";

import { presentResearchRunHistory } from "./research-run-history-workspace.ts";

const run = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/research_run/v1/eligible.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as ResearchRun;

test("presents latest deterministic disposition without treating it as a trade signal", () => {
  const history: ResearchRunHistory = {
    latest: null,
    items: [{
      run,
      readiness: {
        readinessGateResultId: "40000000-0000-4000-8000-000000000001",
        committeeStatus: "complete",
        readinessStatus: "passed",
        requestedDisposition: "decision_ready",
        finalDisposition: "decision_ready",
        gatePolicyVersion: "biotech_decision_readiness.v1",
        evaluatedAt: "2026-05-06T22:03:06Z",
      },
    }],
  };
  history.latest = history.items[0];

  const presentation = presentResearchRunHistory(history);

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  assert.deepEqual(presentation.latest, {
    runId: run.id,
    auditHref: `/research-runs/${run.id}`,
    cutoff: run.as_of_cutoff,
    createdAt: run.created_at,
    eligibility: { label: "Eligible", variant: "verified" },
    workflowState: { label: "Readiness passed", variant: "verified" },
    requestedDisposition: "Decision ready",
    finalDisposition: "Decision ready",
    committeeStatus: "Complete",
    evaluatedAt: "2026-05-06T22:03:06Z",
    isLatest: true,
  });
});
