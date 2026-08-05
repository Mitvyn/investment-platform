import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { ResearchRun } from "../../../packages/types/research-run.ts";

import { createResearchRunHistoryLoader } from "./research-run-history-loader.ts";

const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/research_run/v1/eligible.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as ResearchRun;

const readinessFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/readiness_thesis/v1/decision-ready.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, unknown>;

function viewRows(run: ResearchRun) {
  return run.eligibility.checks.map((check, index) => ({
    operator_id: run.operator_id,
    research_run_id: run.id,
    security_id: run.security_id,
    security_identity_snapshot: run.security_identity,
    question_type: run.question_type,
    question_type_version_id: run.question_type_version,
    workflow_config_version_id: run.workflow_config_version,
    thesis_contract_id: run.thesis_contract_id,
    as_of_cutoff: run.as_of_cutoff,
    operator_focus_original: run.operator_focus_original,
    operator_focus_normalized: run.operator_focus_normalized,
    status: run.status,
    idempotency_key: run.idempotency_key,
    created_at: run.created_at,
    eligibility_policy_version: run.eligibility.policy_version,
    eligible: run.eligibility.eligible,
    evaluated_at: run.eligibility.evaluated_at,
    check_ordinal: index + 1,
    rule_id: check.rule_id,
    rule_version: check.rule_version,
    passed: check.passed,
    evidence_reference: check.evidence_reference,
    reason_code: check.reason_code,
    explanation: check.explanation,
    check_evaluated_at: check.evaluated_at,
  }));
}

test("lists finalized Research Runs newest first for one stable security", async () => {
  const older = structuredClone(fixture);
  older.id = "10000000-0000-4000-8000-000000000001";
  older.created_at = "2026-05-01T12:00:00Z";
  const newer = structuredClone(fixture);
  newer.id = "10000000-0000-4000-8000-000000000002";
  newer.created_at = "2026-05-02T12:00:00Z";
  const requests: unknown[][] = [];
  const load = createResearchRunHistoryLoader(
    async (...args) => {
      requests.push(args);
      return [...viewRows(older), ...viewRows(newer)].reverse();
    },
    async (...args) => {
      requests.push(args);
      return [];
    },
  );

  const result = await load(fixture.operator_id, fixture.security_id);

  assert.equal(result.latest?.run.id, newer.id);
  assert.deepEqual(
    result.items.map((item) => [item.run.id, item.readiness]),
    [
      [newer.id, null],
      [older.id, null],
    ],
  );
  assert.deepEqual(requests, [
    [fixture.operator_id, fixture.security_id],
    [fixture.operator_id, [newer.id, older.id]],
  ]);
});

test("joins one validated deterministic disposition to its Research Run", async () => {
  const readiness = structuredClone(readinessFixture);
  readiness.research_run_id = fixture.id;
  const load = createResearchRunHistoryLoader(
    async () => viewRows(fixture),
    async () => [{
      operator_id: fixture.operator_id,
      research_run_id: fixture.id,
      committee_result_id: String(readiness.committee_result_id),
      committee_memo_id: String(readiness.committee_memo_id),
      canonical_readiness: readiness,
    }],
  );

  const result = await load(fixture.operator_id, fixture.security_id);

  assert.deepEqual(result.latest?.readiness, {
    readinessGateResultId: readiness.readiness_gate_result_id,
    committeeStatus: "complete",
    readinessStatus: "passed",
    requestedDisposition: "decision_ready",
    finalDisposition: "decision_ready",
    gatePolicyVersion: "biotech-readiness.v1",
    evaluatedAt: "2026-05-06T22:03:06Z",
  });
});

test("rejects duplicate readiness outcomes for one Research Run", async () => {
  const readiness = structuredClone(readinessFixture);
  readiness.research_run_id = fixture.id;
  const row = {
    operator_id: fixture.operator_id,
    research_run_id: fixture.id,
    committee_result_id: String(readiness.committee_result_id),
    committee_memo_id: String(readiness.committee_memo_id),
    canonical_readiness: readiness,
  };
  const load = createResearchRunHistoryLoader(
    async () => viewRows(fixture),
    async () => [row, row],
  );

  await assert.rejects(
    load(fixture.operator_id, fixture.security_id),
    /at most one readiness outcome/,
  );
});

test("rejects readiness data outside requested Research Run history", async () => {
  const readiness = structuredClone(readinessFixture);
  const foreignRunId = "10000000-0000-4000-8000-000000000099";
  readiness.research_run_id = foreignRunId;
  const load = createResearchRunHistoryLoader(
    async () => viewRows(fixture),
    async () => [{
      operator_id: fixture.operator_id,
      research_run_id: foreignRunId,
      committee_result_id: String(readiness.committee_result_id),
      committee_memo_id: String(readiness.committee_memo_id),
      canonical_readiness: readiness,
    }],
  );

  await assert.rejects(
    load(fixture.operator_id, fixture.security_id),
    /outside requested Research Run history/,
  );
});

test("empty finalized history does not issue an empty readiness query", async () => {
  let readinessCalls = 0;
  const load = createResearchRunHistoryLoader(
    async () => [],
    async () => {
      readinessCalls += 1;
      return [];
    },
  );

  assert.deepEqual(
    await load(fixture.operator_id, fixture.security_id),
    { latest: null, items: [] },
  );
  assert.equal(readinessCalls, 0);
});
