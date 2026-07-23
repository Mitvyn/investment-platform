import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  parseGraderExecution,
  type GraderExecution,
} from "../../../packages/types/grader-execution.ts";

import { createGraderExecutionLoader } from "./grader-execution-loader.ts";

const executionFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/grader_execution/v1/accepted-moonshot.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as GraderExecution;

const bundleContext = {
  evidenceBundleId: executionFixture.evidence_bundle_id,
  evidenceBundleHash: executionFixture.evidence_bundle_hash,
  evidenceIds: [
    "8d80b1a6-0742-5b0c-bf48-4e0d32cb8200",
    "3663f956-71fe-55bd-a305-5a686bffcf69",
  ],
} as const;

test("authenticated operator loads canonical grader executions for one Research Run", async () => {
  const requests: Array<{ operatorId: string; runId: string }> = [];
  const loadExecutions = createGraderExecutionLoader(
    async (operatorId, runId) => {
      requests.push({ operatorId, runId });
      return [{ canonical_execution: executionFixture }];
    },
    parseGraderExecution,
  );

  const executions = await loadExecutions(
    executionFixture.operator_id,
    executionFixture.research_run_id,
    bundleContext,
  );

  assert.deepEqual(requests, [
    {
      operatorId: executionFixture.operator_id,
      runId: executionFixture.research_run_id,
    },
  ]);
  assert.deepEqual(executions, [executionFixture]);
});

test("grader execution loading rejects a row outside requested owner scope", async () => {
  const loadExecutions = createGraderExecutionLoader(
    async () => [{ canonical_execution: executionFixture }],
    parseGraderExecution,
  );

  await assert.rejects(
    loadExecutions(
      "11111111-1111-4111-8111-111111111111",
      executionFixture.research_run_id,
      bundleContext,
    ),
    /outside requested owner or Research Run scope/,
  );
});
