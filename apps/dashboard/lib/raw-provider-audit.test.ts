import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  hasRawProviderAuditPermission,
  readRawProviderPayload,
} from "./raw-provider-audit.ts";

const operatorId = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792";
const runId = "ee6e1809-76ae-41b8-bc42-7c968b995386";
const payloadId = "b7489aea-ad0f-4607-b5ca-68b91b744d08";

const authorizedClaims = {
  sub: operatorId,
  app_metadata: { iros_permissions: ["raw_provider_audit"] },
};

test("grants only the trusted app_metadata permission", () => {
  assert.equal(hasRawProviderAuditPermission(authorizedClaims), true);
  assert.equal(
    hasRawProviderAuditPermission({
      sub: operatorId,
      user_metadata: { iros_permissions: ["raw_provider_audit"] },
    }),
    false,
  );
  assert.equal(
    hasRawProviderAuditPermission({
      sub: operatorId,
      app_metadata: { iros_permissions: "raw_provider_audit" },
    }),
    false,
  );
});

test("reads an owner-scoped payload only through the audited RPC", async () => {
  const calls: unknown[] = [];
  const expected = {
    contract_version: "raw_provider_audit_payload.v1",
    operator_id: operatorId,
    research_run_id: runId,
    payload_kind: "grader",
    payload_id: payloadId,
    raw_payload_sha256: "a".repeat(64),
    request_payload: { prompt: "sanitized public evidence" },
    response_payload: { execution_state: "accepted" },
    access_audit_event_id: "c51ab783-1df9-48fa-90fd-858354ab9a8f",
    accessed_at: "2026-07-22T11:30:00Z",
  };
  const client = {
    async rpc(name: string, args: Record<string, string>) {
      calls.push([name, args]);
      return { data: expected, error: null };
    },
  };

  const result = await readRawProviderPayload(client, authorizedClaims, {
    researchRunId: runId,
    payloadKind: "grader",
    payloadId,
  });

  assert.deepEqual(result, expected);
  assert.deepEqual(calls, [
    [
      "iros_read_raw_provider_payload",
      {
        p_research_run_id: runId,
        p_payload_kind: "grader",
        p_payload_id: payloadId,
      },
    ],
  ]);
});

test("denies missing permission before calling the RPC", async () => {
  let called = false;
  const client = {
    async rpc() {
      called = true;
      return { data: null, error: null };
    },
  };

  await assert.rejects(
    readRawProviderPayload(client, { sub: operatorId }, {
      researchRunId: runId,
      payloadKind: "grader",
      payloadId,
    }),
    /raw provider audit permission required/,
  );
  assert.equal(called, false);
});

test("rejects a payload response that does not match the authenticated owner", async () => {
  const client = {
    async rpc() {
      return {
        data: {
          contract_version: "raw_provider_audit_payload.v1",
          operator_id: "523607c8-8ac0-44d8-a244-417255ddef38",
          research_run_id: runId,
          payload_kind: "grader",
          payload_id: payloadId,
          raw_payload_sha256: "a".repeat(64),
          request_payload: {},
          response_payload: null,
          access_audit_event_id: "c51ab783-1df9-48fa-90fd-858354ab9a8f",
          accessed_at: "2026-07-22T11:30:00Z",
        },
        error: null,
      };
    },
  };

  await assert.rejects(
    readRawProviderPayload(client, authorizedClaims, {
      researchRunId: runId,
      payloadKind: "grader",
      payloadId,
    }),
    /raw provider audit owner mismatch/,
  );
});

test("server-only route authenticates claims and delegates to the audited reader", () => {
  const route = readFileSync(
    new URL(
      "../app/api/research-runs/[runId]/raw-provider-payloads/[kind]/[payloadId]/route.ts",
      import.meta.url,
    ),
    "utf8",
  );
  assert.match(route, /auth\.getClaims\(\)/);
  assert.match(route, /readRawProviderPayload/);
  assert.match(route, /Cache-Control[\s\S]*no-store/);
  assert.doesNotMatch(route, /iros_model_attempt_payloads/);
  assert.doesNotMatch(route, /iros_synthesis_attempt_payloads/);
});
