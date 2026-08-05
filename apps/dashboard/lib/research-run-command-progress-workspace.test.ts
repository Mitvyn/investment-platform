import assert from "node:assert/strict";
import test from "node:test";

import type { ResearchRunCommandProgress } from "./research-run-command-progress-loader.ts";
import { presentResearchRunCommandProgress } from "./research-run-command-progress-workspace.ts";

const progress: ResearchRunCommandProgress = {
  contract_version: "research_run_command_progress.v1",
  operator_id: "027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
  command_id: "11111111-1111-4111-8111-111111111111",
  command_state: "running",
  attempt_id: "44444444-4444-4444-8444-444444444444",
  attempt_number: 2,
  attempt_state: "running",
  active_stage: "committee_memo",
  completed_stages: [
    "research_run",
    "evidence_bundle",
    "valuation_snapshot",
    "grader_committee",
  ],
  lease_started_at: "2026-07-30T02:00:00Z",
  lease_expires_at: "2026-07-30T02:05:00Z",
  failure_stage: null,
  error_code: null,
  retryable: null,
  updated_at: "2026-07-30T02:01:00Z",
};

test("presents active attempt with fresh or expired lease from current time", () => {
  const fresh = presentResearchRunCommandProgress(
    progress,
    new Date("2026-07-30T02:04:59Z"),
  );
  const expired = presentResearchRunCommandProgress(
    progress,
    new Date("2026-07-30T02:05:00Z"),
  );

  assert.deepEqual(fresh.lease, {
    label: "Lease fresh",
    variant: "verified",
    expiresAt: "2026-07-30T02:05:00Z",
  });
  assert.deepEqual(expired.lease, {
    label: "Lease expired",
    variant: "destructive",
    expiresAt: "2026-07-30T02:05:00Z",
  });
  assert.equal(fresh.attempt, "Attempt 2 of 2");
  assert.equal(fresh.activeStage, "Committee memo");
  assert.equal(fresh.completedStages.at(-1)?.label, "Grader committee");
});

test("presents terminal failure separately from active lease state", () => {
  const failed = presentResearchRunCommandProgress(
    {
      ...progress,
      command_state: "failed",
      attempt_state: "failed",
      active_stage: null,
      failure_stage: "committee_memo",
      error_code: "committee_memo_contract_invalid",
      retryable: false,
    },
    new Date("2026-07-30T02:06:00Z"),
  );

  assert.deepEqual(failed.failure, {
    stage: "Committee memo",
    errorCode: "committee_memo_contract_invalid",
    retryable: false,
  });
  assert.deepEqual(failed.lease, {
    label: "Lease not active",
    variant: "outline",
    expiresAt: "2026-07-30T02:05:00Z",
  });
});

test("presents blocked preflight separately from queued work", () => {
  const inactive = {
    ...progress,
    attempt_id: null,
    attempt_number: null,
    attempt_state: null,
    active_stage: null,
    completed_stages: [],
    lease_started_at: null,
    lease_expires_at: null,
  } satisfies ResearchRunCommandProgress;

  const blocked = presentResearchRunCommandProgress(
    { ...inactive, command_state: "blocked" },
    new Date("2026-07-30T02:06:00Z"),
  );
  const queued = presentResearchRunCommandProgress(
    { ...inactive, command_state: "queued" },
    new Date("2026-07-30T02:06:00Z"),
  );

  assert.deepEqual(blocked.status, {
    label: "Launch blocked",
    variant: "attention",
  });
  assert.deepEqual(queued.status, {
    label: "Queued",
    variant: "outline",
  });
  assert.equal(blocked.attempt, "No attempt");
});
