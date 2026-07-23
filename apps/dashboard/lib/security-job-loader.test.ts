import assert from "node:assert/strict";
import test from "node:test";

import { createSecurityJobLoader } from "./security-job-loader.ts";

const operatorId = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792";
const jobId = "ee6e1809-76ae-41b8-bc42-7c968b995386";

test("loads one owner-scoped security onboarding status", async () => {
  const requests: unknown[] = [];
  const loadJob = createSecurityJobLoader(async (owner, job) => {
    requests.push([owner, job]);
    return [
      {
        id: jobId,
        operator_id: operatorId,
        job_type: "security_onboarding",
        job_state: "running",
        idempotency_key: "security-registration:v1:CRSP",
        ticker: "CRSP",
        security_id: null,
        error_code: null,
        created_at: "2026-07-23T04:00:00Z",
        updated_at: "2026-07-23T04:01:00Z",
      },
    ];
  });

  const job = await loadJob(operatorId, jobId);

  assert.deepEqual(requests, [[operatorId, jobId]]);
  assert.equal(job?.state, "running");
  assert.equal(job?.ticker, "CRSP");
  assert.equal(job?.operator_id, operatorId);
});
