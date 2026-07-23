import assert from "node:assert/strict";
import test from "node:test";

import { enqueueSecurityRegistration } from "./security-registration.ts";

const operatorId = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792";
const jobId = "ee6e1809-76ae-41b8-bc42-7c968b995386";

test("authenticated operator queues normalized security registration and receives owner-scoped receipt", async () => {
  const calls: unknown[] = [];
  const expected = {
    contract_version: "workflow_job_receipt.v1",
    job_id: jobId,
    operator_id: operatorId,
    job_type: "security_onboarding",
    state: "queued",
    idempotency_key: "security-registration:v1:CRSP",
    ticker: "CRSP",
    security_id: null,
    blocking_reasons: [],
    error_code: null,
    created_at: "2026-07-23T04:00:00Z",
    updated_at: "2026-07-23T04:00:00Z",
  };
  const client = {
    async rpc(name: string, args: Record<string, string>) {
      calls.push([name, args]);
      return { data: [expected], error: null };
    },
  };

  const result = await enqueueSecurityRegistration(
    client,
    { sub: operatorId },
    {
      contract_version: "security_registration_request.v1",
      ticker: " crsp ",
    },
  );

  assert.deepEqual(result, expected);
  assert.deepEqual(calls, [
    ["iros_enqueue_security_registration", { p_ticker: "CRSP" }],
  ]);
});

test("rejects a receipt owned by another operator", async () => {
  const client = {
    async rpc() {
      return {
        data: [
          {
            contract_version: "workflow_job_receipt.v1",
            job_id: jobId,
            operator_id: "523607c8-8ac0-44d8-a244-417255ddef38",
            job_type: "security_onboarding",
            state: "queued",
            idempotency_key: "security-registration:v1:CRSP",
            ticker: "CRSP",
            security_id: null,
            blocking_reasons: [],
            error_code: null,
            created_at: "2026-07-23T04:00:00Z",
            updated_at: "2026-07-23T04:00:00Z",
          },
        ],
        error: null,
      };
    },
  };

  await assert.rejects(
    enqueueSecurityRegistration(client, { sub: operatorId }, {
      contract_version: "security_registration_request.v1",
      ticker: "CRSP",
    }),
    /workflow job owner mismatch/,
  );
});
