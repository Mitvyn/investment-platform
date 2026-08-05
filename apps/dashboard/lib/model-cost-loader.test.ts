import assert from "node:assert/strict";
import test from "node:test";

import { createModelCostLoader } from "./model-cost-loader.ts";

const owner = "11111111-1111-4111-8111-111111111111";
const run = "22222222-2222-4222-8222-222222222222";

const budget = {
  operator_id: owner,
  research_run_id: run,
  budget_id: "33333333-3333-4333-8333-333333333333",
};
const reservation = {
  operator_id: owner,
  research_run_id: run,
  reservation_id: "44444444-4444-4444-8444-444444444444",
};
const attempt = {
  operator_id: owner,
  research_run_id: run,
  attempt_id: "55555555-5555-4555-8555-555555555555",
};

test("loads persisted model accounting from three owner and Research Run scoped views", async () => {
  const requests: Array<{ source: string; owner: string; run: string }> = [];
  const load = createModelCostLoader(
    async (operatorId, researchRunId) => {
      requests.push({ source: "budgets", owner: operatorId, run: researchRunId });
      return [budget];
    },
    async (operatorId, researchRunId) => {
      requests.push({ source: "reservations", owner: operatorId, run: researchRunId });
      return [reservation];
    },
    async (operatorId, researchRunId) => {
      requests.push({ source: "attempts", owner: operatorId, run: researchRunId });
      return [attempt];
    },
  );

  assert.deepEqual(await load(owner, run), {
    budgets: [budget],
    reservations: [reservation],
    attempts: [attempt],
  });
  assert.deepEqual(requests, [
    { source: "budgets", owner, run },
    { source: "reservations", owner, run },
    { source: "attempts", owner, run },
  ]);
});

test("rejects accounting rows outside requested owner or Research Run scope", async () => {
  const load = createModelCostLoader(
    async () => [budget],
    async () => [reservation],
    async () => [{ ...attempt, operator_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" }],
  );

  await assert.rejects(load(owner, run), /outside requested owner or Research Run scope/);
});
