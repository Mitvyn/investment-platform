import assert from "node:assert/strict";
import test from "node:test";

import { createCommitteeMemoLoader } from "./committee-memo-loader.ts";

const memo = {
  research_run_id: "984cce87-acde-4c65-8566-86fe27d21df3",
  committee_id: "0fdbf17e-175d-4905-822a-b8c7ea84517e",
  execution_metadata: {
    prompt_version: "committee_reconcile_v1",
    model_config_id: "synthesis-config-v1",
    attempts: [{
      attempt_id: "34000000-0000-4000-8000-000000000001",
      result: "accepted",
      validation_errors: [],
      reasoning_tokens: 300,
      usage_complete: true,
      estimated_cost_usd: "0.000000",
    }],
  },
};

test("authenticated operator loads one canonical memo for its Research Run", async () => {
  const requests: Array<{ operatorId: string; runId: string }> = [];
  const loadMemo = createCommitteeMemoLoader(
    async (operatorId, runId) => {
      requests.push({ operatorId, runId });
      return [
        {
          operator_id: "11111111-1111-4111-8111-111111111111",
          research_run_id: memo.research_run_id,
          committee_result_id: memo.committee_id,
          canonical_memo: memo,
        },
      ];
    },
    (value) => value as typeof memo,
  );

  const loaded = await loadMemo(
    "11111111-1111-4111-8111-111111111111",
    memo.research_run_id,
  );

  assert.deepEqual(requests, [
    {
      operatorId: "11111111-1111-4111-8111-111111111111",
      runId: memo.research_run_id,
    },
  ]);
  assert.equal(loaded, memo);
  assert.deepEqual(loaded.execution_metadata.attempts[0], {
    attempt_id: "34000000-0000-4000-8000-000000000001",
    result: "accepted",
    validation_errors: [],
    reasoning_tokens: 300,
    usage_complete: true,
    estimated_cost_usd: "0.000000",
  });
});

test("memo loader rejects duplicate canonical rows", async () => {
  const row = {
    operator_id: "11111111-1111-4111-8111-111111111111",
    research_run_id: memo.research_run_id,
    committee_result_id: memo.committee_id,
    canonical_memo: memo,
  };
  const loadMemo = createCommitteeMemoLoader(
    async () => [row, row],
    (value) => value as typeof memo,
  );

  await assert.rejects(
    loadMemo(row.operator_id, row.research_run_id),
    /exactly one canonical memo/,
  );
});

test("memo loader rejects rows outside requested owner, run, or committee", async () => {
  const row = {
    operator_id: "11111111-1111-4111-8111-111111111111",
    research_run_id: memo.research_run_id,
    committee_result_id: memo.committee_id,
    canonical_memo: memo,
  };
  const loadMemo = createCommitteeMemoLoader(
    async () => [row],
    (value) => value as typeof memo,
  );

  await assert.rejects(
    loadMemo(
      "22222222-2222-4222-8222-222222222222",
      row.research_run_id,
    ),
    /outside requested owner, Research Run, or committee scope/,
  );
});

test("memo loader returns null when no accepted memo exists", async () => {
  const loadMemo = createCommitteeMemoLoader(
    async () => [],
    (value) => value as typeof memo,
  );

  assert.equal(
    await loadMemo(
      "11111111-1111-4111-8111-111111111111",
      memo.research_run_id,
    ),
    null,
  );
});
