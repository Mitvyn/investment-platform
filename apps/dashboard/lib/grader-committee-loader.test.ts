import assert from "node:assert/strict";
import test from "node:test";

import type { CommitteeState } from "../../../packages/types/committee.ts";

import { createGraderCommitteeLoader } from "./grader-committee-loader.ts";

const committee = {
  research_run_id: "984cce87-acde-4c65-8566-86fe27d21df3",
} as CommitteeState;

test("authenticated operator loads at most one canonical committee for its Research Run", async () => {
  const requests: Array<{ operatorId: string; runId: string }> = [];
  const loadCommittee = createGraderCommitteeLoader(
    async (operatorId, runId) => {
      requests.push({ operatorId, runId });
      return [
        {
          operator_id: "11111111-1111-4111-8111-111111111111",
          research_run_id: committee.research_run_id,
          canonical_committee: committee,
        },
      ];
    },
    (value) => value as CommitteeState,
  );

  const loaded = await loadCommittee(
    "11111111-1111-4111-8111-111111111111",
    committee.research_run_id,
  );

  assert.deepEqual(requests, [
    {
      operatorId: "11111111-1111-4111-8111-111111111111",
      runId: committee.research_run_id,
    },
  ]);
  assert.equal(loaded, committee);
});

test("committee loader rejects duplicate rows and rows outside owner scope", async () => {
  const row = {
    operator_id: "11111111-1111-4111-8111-111111111111",
    research_run_id: committee.research_run_id,
    canonical_committee: committee,
  };
  const duplicateLoader = createGraderCommitteeLoader(
    async () => [row, row],
    (value) => value as CommitteeState,
  );
  await assert.rejects(
    duplicateLoader(row.operator_id, row.research_run_id),
    /exactly one canonical committee/,
  );

  const wrongOwnerLoader = createGraderCommitteeLoader(
    async () => [row],
    (value) => value as CommitteeState,
  );
  await assert.rejects(
    wrongOwnerLoader(
      "22222222-2222-4222-8222-222222222222",
      row.research_run_id,
    ),
    /outside requested owner or Research Run scope/,
  );
});

test("committee loader returns null when no finalized committee exists", async () => {
  const loadCommittee = createGraderCommitteeLoader(
    async () => [],
    (value) => value as CommitteeState,
  );

  assert.equal(
    await loadCommittee(
      "11111111-1111-4111-8111-111111111111",
      committee.research_run_id,
    ),
    null,
  );
});
