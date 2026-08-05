import assert from "node:assert/strict";
import test from "node:test";

import { createResearchRunCommandProgressLoader } from "./research-run-command-progress-loader.ts";

const operatorId = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792";
const commandId = "11111111-1111-4111-8111-111111111111";

const runningProgress = {
  contract_version: "research_run_command_progress.v1",
  operator_id: operatorId,
  command_id: commandId,
  command_state: "running",
  attempt_id: "44444444-4444-4444-8444-444444444444",
  attempt_number: 1,
  attempt_state: "running",
  active_stage: "valuation_snapshot",
  completed_stages: ["research_run", "evidence_bundle"],
  lease_started_at: "2026-07-30T02:00:00Z",
  lease_expires_at: "2026-07-30T02:05:00Z",
  failure_stage: null,
  error_code: null,
  retryable: null,
  updated_at: "2026-07-30T02:01:00Z",
};

test("loads one owner-scoped running Research Run command progress", async () => {
  const requests: unknown[][] = [];
  const load = createResearchRunCommandProgressLoader(async (...args) => {
    requests.push(args);
    return [{
      operator_id: operatorId,
      command_id: commandId,
      canonical_progress: runningProgress,
    }];
  });

  const progress = await load(operatorId, commandId);

  assert.deepEqual(requests, [[operatorId, commandId]]);
  assert.deepEqual(progress, {
    ...runningProgress,
    completed_stages: ["research_run", "evidence_bundle"],
  });
});

test("rejects a checkpoint list that is not the canonical stage prefix", async () => {
  const load = createResearchRunCommandProgressLoader(async () => [{
    operator_id: operatorId,
    command_id: commandId,
    canonical_progress: {
      ...runningProgress,
      active_stage: "valuation_snapshot",
      completed_stages: ["evidence_bundle", "research_run"],
    },
  }]);

  await assert.rejects(
    load(operatorId, commandId),
    /invalid Research Run command stage progress/,
  );
});

test("loads terminal failure without collapsing it into missing progress", async () => {
  const failedProgress = {
    ...runningProgress,
    command_state: "failed",
    attempt_state: "failed",
    active_stage: null,
    completed_stages: ["research_run", "evidence_bundle"],
    failure_stage: "valuation_snapshot",
    error_code: "valuation_snapshot_contract_invalid",
    retryable: false,
  };
  const load = createResearchRunCommandProgressLoader(async () => [{
    operator_id: operatorId,
    command_id: commandId,
    canonical_progress: failedProgress,
  }]);

  const progress = await load(operatorId, commandId);

  assert.equal(progress?.command_state, "failed");
  assert.equal(progress?.attempt_number, 1);
  assert.equal(progress?.failure_stage, "valuation_snapshot");
  assert.equal(progress?.error_code, "valuation_snapshot_contract_invalid");
  assert.equal(progress?.retryable, false);
});

test("loads a completed command only with the full checkpoint prefix", async () => {
  const completedProgress = {
    ...runningProgress,
    command_state: "completed",
    attempt_state: "completed",
    active_stage: null,
    completed_stages: [
      "research_run",
      "evidence_bundle",
      "valuation_snapshot",
      "grader_committee",
      "committee_memo",
      "readiness_thesis",
    ],
  };
  const load = createResearchRunCommandProgressLoader(async () => [{
    operator_id: operatorId,
    command_id: commandId,
    canonical_progress: completedProgress,
  }]);

  const progress = await load(operatorId, commandId);

  assert.equal(progress?.command_state, "completed");
  assert.deepEqual(progress?.completed_stages, completedProgress.completed_stages);
  assert.equal(progress?.active_stage, null);
});

test("returns null for no progress and rejects ambiguous or cross-owner rows", async () => {
  const empty = createResearchRunCommandProgressLoader(async () => []);
  assert.equal(await empty(operatorId, commandId), null);

  const viewRow = {
    operator_id: operatorId,
    command_id: commandId,
    canonical_progress: runningProgress,
  };
  const ambiguous = createResearchRunCommandProgressLoader(
    async () => [viewRow, viewRow],
  );
  await assert.rejects(
    ambiguous(operatorId, commandId),
    /progress is ambiguous/,
  );

  const crossOwner = createResearchRunCommandProgressLoader(async () => [{
    ...viewRow,
    operator_id: "33333333-3333-4333-8333-333333333333",
  }]);
  await assert.rejects(
    crossOwner(operatorId, commandId),
    /outside requested owner scope/,
  );
});

test("loads a queued command before any worker attempt exists", async () => {
  const queuedProgress = {
    ...runningProgress,
    command_state: "queued",
    attempt_id: null,
    attempt_number: null,
    attempt_state: null,
    active_stage: null,
    completed_stages: [],
    lease_started_at: null,
    lease_expires_at: null,
  };
  const load = createResearchRunCommandProgressLoader(async () => [{
    operator_id: operatorId,
    command_id: commandId,
    canonical_progress: queuedProgress,
  }]);

  const progress = await load(operatorId, commandId);

  assert.equal(progress?.command_state, "queued");
  assert.equal(progress?.attempt_number, null);
  assert.equal(progress?.active_stage, null);
  assert.deepEqual(progress?.completed_stages, []);
});

test("preserves a retryable failed attempt while command is queued again", async () => {
  const retryProgress = {
    ...runningProgress,
    command_state: "queued",
    attempt_state: "failed",
    active_stage: null,
    completed_stages: ["research_run", "evidence_bundle"],
    failure_stage: "valuation_snapshot",
    error_code: "lease_expired",
    retryable: true,
  };
  const load = createResearchRunCommandProgressLoader(async () => [{
    operator_id: operatorId,
    command_id: commandId,
    canonical_progress: retryProgress,
  }]);

  const progress = await load(operatorId, commandId);

  assert.equal(progress?.command_state, "queued");
  assert.equal(progress?.attempt_state, "failed");
  assert.equal(progress?.failure_stage, "valuation_snapshot");
  assert.equal(progress?.retryable, true);
});

test("loads a blocked preflight distinctly from queued or missing progress", async () => {
  const blockedProgress = {
    ...runningProgress,
    command_state: "blocked",
    attempt_id: null,
    attempt_number: null,
    attempt_state: null,
    active_stage: null,
    completed_stages: [],
    lease_started_at: null,
    lease_expires_at: null,
  };
  const load = createResearchRunCommandProgressLoader(async () => [{
    operator_id: operatorId,
    command_id: commandId,
    canonical_progress: blockedProgress,
  }]);

  const progress = await load(operatorId, commandId);

  assert.equal(progress?.command_state, "blocked");
  assert.equal(progress?.attempt_number, null);
  assert.deepEqual(progress?.completed_stages, []);
});
