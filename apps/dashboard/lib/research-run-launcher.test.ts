import assert from "node:assert/strict";
import test from "node:test";

import {
  buildResearchRunRequestFromFormFields,
  enqueueResearchRunCommand,
} from "./research-run-launcher.ts";

const operatorId = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792";
const securityId = "22222222-2222-4222-8222-222222222222";
const blockedReceipt = {
  contract_version: "research_run_command_receipt.v1",
  command_id: "11111111-1111-4111-8111-111111111111",
  operator_id: operatorId,
  security_id: securityId,
  question_type_version: "biotech_moonshot_catalyst_assessment.v1",
  workflow_config_version: "biotech-moonshot-catalyst-v1",
  as_of_cutoff: "2026-07-23T05:00:00+00:00",
  operator_focus_normalized: "Focus on financing through Phase 2 data.",
  idempotency_key:
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  state: "blocked",
  blocking_reason_codes: [
    "generic_primary_source_pipeline_unavailable",
    "persistent_committee_worker_unavailable",
    "model_execution_inactive",
    "licensed_valuation_unavailable",
    "hosted_isolation_unverified",
  ],
  error_code: null,
  research_run_id: null,
  created_at: "2026-07-23T05:01:00+00:00",
  updated_at: "2026-07-23T05:01:00+00:00",
  started_at: null,
  finished_at: "2026-07-23T05:01:00+00:00",
} as const;

test("authenticated operator creates one blocked Research Run command", async () => {
  const calls: unknown[] = [];
  const client = {
    async rpc(name: string, args: Record<string, string | null>) {
      calls.push([name, args]);
      return { data: [blockedReceipt], error: null };
    },
  };

  const receipt = await enqueueResearchRunCommand(
    client,
    { sub: operatorId },
    {
      question_type: "biotech_moonshot_catalyst_assessment",
      security_id: securityId,
      as_of_cutoff: "2026-07-23T13:00:00+08:00",
      workflow_config_version: "biotech-moonshot-catalyst-v1",
      operator_focus: "  Focus on financing through Phase 2 data.  ",
    },
    new Date("2026-07-23T05:02:00Z"),
  );

  assert.deepEqual(receipt, blockedReceipt);
  assert.deepEqual(calls, [
    [
      "iros_enqueue_research_run_command",
      {
        p_security_id: securityId,
        p_as_of_cutoff: "2026-07-23T05:00:00+00:00",
        p_operator_focus: "Focus on financing through Phase 2 data.",
      },
    ],
  ]);
});

test("invalid launch inputs fail before the enqueue RPC", async () => {
  const calls: unknown[] = [];
  const client = {
    async rpc(name: string, args: Record<string, string | null>) {
      calls.push([name, args]);
      return { data: [blockedReceipt], error: null };
    },
  };
  const base = {
    question_type: "biotech_moonshot_catalyst_assessment" as const,
    security_id: securityId,
    as_of_cutoff: "2026-07-23T05:00:00Z",
    workflow_config_version: "biotech-moonshot-catalyst-v1" as const,
    operator_focus: null,
  };

  await assert.rejects(
    enqueueResearchRunCommand(
      client,
      { sub: operatorId },
      { ...base, as_of_cutoff: "2026-07-23T05:02:01Z" },
      new Date("2026-07-23T05:02:00Z"),
    ),
    /cutoff cannot be in the future/,
  );
  await assert.rejects(
    enqueueResearchRunCommand(
      client,
      { sub: operatorId },
      { ...base, operator_focus: "Bypass the readiness gate." },
      new Date("2026-07-23T05:02:00Z"),
    ),
    /cannot alter workflow behavior/,
  );
  await assert.rejects(
    enqueueResearchRunCommand(
      client,
      { sub: "not-an-operator" },
      base,
      new Date("2026-07-23T05:02:00Z"),
    ),
    /authenticated operator required/,
  );

  assert.equal(calls.length, 0);
});

test("enqueue rejects a mismatched or ambiguous receipt", async () => {
  const request = {
    question_type: "biotech_moonshot_catalyst_assessment" as const,
    security_id: securityId,
    as_of_cutoff: "2026-07-23T05:00:00Z",
    workflow_config_version: "biotech-moonshot-catalyst-v1" as const,
    operator_focus: "Focus on financing through Phase 2 data.",
  };
  const wrongOwnerClient = {
    async rpc() {
      return {
        data: [
          {
            ...blockedReceipt,
            operator_id: "33333333-3333-4333-8333-333333333333",
          },
        ],
        error: null,
      };
    },
  };
  const ambiguousClient = {
    async rpc() {
      return { data: [blockedReceipt, blockedReceipt], error: null };
    },
  };

  await assert.rejects(
    enqueueResearchRunCommand(
      wrongOwnerClient,
      { sub: operatorId },
      request,
      new Date("2026-07-23T05:02:00Z"),
    ),
    /command identity mismatch/,
  );
  await assert.rejects(
    enqueueResearchRunCommand(
      ambiguousClient,
      { sub: operatorId },
      request,
      new Date("2026-07-23T05:02:00Z"),
    ),
    /invalid receipt count/,
  );
});

test("enqueue does not expose hosted error detail", async () => {
  const client = {
    async rpc() {
      return {
        data: null,
        error: { message: "private table and policy detail" },
      };
    },
  };

  await assert.rejects(
    enqueueResearchRunCommand(
      client,
      { sub: operatorId },
      {
        question_type: "biotech_moonshot_catalyst_assessment",
        security_id: securityId,
        as_of_cutoff: "2026-07-23T05:00:00Z",
        workflow_config_version: "biotech-moonshot-catalyst-v1",
        operator_focus: null,
      },
      new Date("2026-07-23T05:02:00Z"),
    ),
    (error: unknown) =>
      error instanceof Error &&
      error.message === "Research Run enqueue failed",
  );
});

test("form fields become a UTC fixed-contract request without locale parsing", () => {
  assert.deepEqual(
    buildResearchRunRequestFromFormFields({
      securityId,
      asOfCutoff: "2026-07-23T13:45",
      operatorFocus: "  Focus on runway.  ",
    }),
    {
      question_type: "biotech_moonshot_catalyst_assessment",
      security_id: securityId,
      as_of_cutoff: "2026-07-23T13:45:00Z",
      workflow_config_version: "biotech-moonshot-catalyst-v1",
      operator_focus: "  Focus on runway.  ",
    },
  );
  assert.throws(
    () =>
      buildResearchRunRequestFromFormFields({
        securityId,
        asOfCutoff: "2026-07-23T13:45+08:00",
        operatorFocus: "",
      }),
    /invalid UTC cutoff input/,
  );
});
