import assert from "node:assert/strict";
import test from "node:test";

import {
  buildResearchRunRequestFromFormFields,
  enqueueResearchRunCommand,
} from "./research-run-launcher.ts";

const operatorId = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792";
const securityId = "22222222-2222-4222-8222-222222222222";
const queuedReceipt = {
  contract_version: "research_run_command_receipt.v2",
  command_id: "11111111-1111-4111-8111-111111111111",
  operator_id: operatorId,
  security_id: securityId,
  question_type_version: "biotech_moonshot_catalyst_assessment.v1",
  workflow_config_version: "biotech-moonshot-catalyst-v1",
  as_of_cutoff: "2026-07-23T05:00:00+00:00",
  operator_focus_normalized: "Focus on financing through Phase 2 data.",
  idempotency_key:
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  capture_id: "44444444-4444-4444-8444-444444444444",
  capture_revision: 3,
  capture_content_hash:
    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  state: "queued",
  blocking_reason_codes: [],
  error_code: null,
  research_run_id: null,
  created_at: "2026-07-23T05:01:00+00:00",
  updated_at: "2026-07-23T05:01:00+00:00",
  started_at: null,
  finished_at: null,
} as const;

const preparedCapture = {
  capture_id: queuedReceipt.capture_id,
  capture_revision: queuedReceipt.capture_revision,
  capture_content_hash: queuedReceipt.capture_content_hash,
};

test("authenticated operator queues one capture-bound Research Run command", async () => {
  const calls: unknown[] = [];
  const client = {
    async rpc(name: string, args: Record<string, string | number | null>) {
      calls.push([name, args]);
      return { data: [queuedReceipt], error: null };
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
    preparedCapture,
    new Date("2026-07-23T05:02:00Z"),
  );

  assert.deepEqual(receipt, queuedReceipt);
  assert.deepEqual(calls, [
    [
      "iros_enqueue_research_run_command_v2",
      {
        p_security_id: securityId,
        p_as_of_cutoff: "2026-07-23T05:00:00+00:00",
        p_operator_focus: "Focus on financing through Phase 2 data.",
        p_question_type_version:
          "biotech_moonshot_catalyst_assessment.v1",
        p_workflow_config_version: "biotech-moonshot-catalyst-v1",
        p_capture_id: preparedCapture.capture_id,
        p_capture_revision: preparedCapture.capture_revision,
        p_capture_content_hash: preparedCapture.capture_content_hash,
      },
    ],
  ]);
});

test("invalid launch inputs fail before the enqueue RPC", async () => {
  const calls: unknown[] = [];
  const client = {
    async rpc(name: string, args: Record<string, string | null>) {
      calls.push([name, args]);
      return { data: [queuedReceipt], error: null };
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
      preparedCapture,
      new Date("2026-07-23T05:02:00Z"),
    ),
    /cutoff cannot be in the future/,
  );
  await assert.rejects(
    enqueueResearchRunCommand(
      client,
      { sub: operatorId },
      { ...base, operator_focus: "Bypass the readiness gate." },
      preparedCapture,
      new Date("2026-07-23T05:02:00Z"),
    ),
    /cannot alter workflow behavior/,
  );
  await assert.rejects(
    enqueueResearchRunCommand(
      client,
      { sub: "not-an-operator" },
      base,
      preparedCapture,
      new Date("2026-07-23T05:02:00Z"),
    ),
    /authenticated operator required/,
  );
  await assert.rejects(
    enqueueResearchRunCommand(
      client,
      { sub: operatorId },
      base,
      { ...preparedCapture, capture_revision: 0 },
      new Date("2026-07-23T05:02:00Z"),
    ),
    /invalid prepared Research capture identity/,
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
            ...queuedReceipt,
            operator_id: "33333333-3333-4333-8333-333333333333",
          },
        ],
        error: null,
      };
    },
  };
  const ambiguousClient = {
    async rpc() {
      return { data: [queuedReceipt, queuedReceipt], error: null };
    },
  };
  const wrongCaptureClient = {
    async rpc() {
      return {
        data: [{ ...queuedReceipt, capture_content_hash: "c".repeat(64) }],
        error: null,
      };
    },
  };
  const historicalReceiptClient = {
    async rpc() {
      const {
        capture_id,
        capture_revision,
        capture_content_hash,
        ...historical
      } = queuedReceipt;
      void capture_id;
      void capture_revision;
      void capture_content_hash;
      return {
        data: [
          {
            ...historical,
            contract_version: "research_run_command_receipt.v1",
          },
        ],
        error: null,
      };
    },
  };

  await assert.rejects(
    enqueueResearchRunCommand(
      wrongOwnerClient,
      { sub: operatorId },
      request,
      preparedCapture,
      new Date("2026-07-23T05:02:00Z"),
    ),
    /command identity mismatch/,
  );
  await assert.rejects(
    enqueueResearchRunCommand(
      ambiguousClient,
      { sub: operatorId },
      request,
      preparedCapture,
      new Date("2026-07-23T05:02:00Z"),
    ),
    /invalid receipt count/,
  );
  await assert.rejects(
    enqueueResearchRunCommand(
      wrongCaptureClient,
      { sub: operatorId },
      request,
      preparedCapture,
      new Date("2026-07-23T05:02:00Z"),
    ),
    /command identity mismatch/,
  );
  await assert.rejects(
    enqueueResearchRunCommand(
      historicalReceiptClient,
      { sub: operatorId },
      request,
      preparedCapture,
      new Date("2026-07-23T05:02:00Z"),
    ),
    /command identity mismatch/,
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
      preparedCapture,
      new Date("2026-07-23T05:02:00Z"),
    ),
    (error: unknown) =>
      error instanceof Error &&
      error.message === "Research Run enqueue failed",
  );
});

test("form fields select an exact strict or personal Research Run contract", () => {
  assert.deepEqual(
    buildResearchRunRequestFromFormFields({
      securityId,
      asOfCutoff: "2026-07-23T13:45",
      operatorFocus: "  Focus on runway.  ",
      researchContract: "licensed_official",
    }),
    {
      question_type: "biotech_moonshot_catalyst_assessment",
      security_id: securityId,
      as_of_cutoff: "2026-07-23T13:45:00Z",
      workflow_config_version: "biotech-moonshot-catalyst-v1",
      operator_focus: "  Focus on runway.  ",
    },
  );
  assert.deepEqual(
    buildResearchRunRequestFromFormFields({
      securityId,
      asOfCutoff: "2026-07-23T13:45",
      operatorFocus: "Focus on runway.",
      researchContract: "personal_research",
    }),
    {
      question_type:
        "biotech_moonshot_catalyst_personal_research_assessment",
      security_id: securityId,
      as_of_cutoff: "2026-07-23T13:45:00Z",
      workflow_config_version:
        "biotech-moonshot-catalyst-personal-research-v1",
      operator_focus: "Focus on runway.",
    },
  );
  assert.throws(
    () =>
      buildResearchRunRequestFromFormFields({
        securityId,
        asOfCutoff: "2026-07-23T13:45+08:00",
        operatorFocus: "",
        researchContract: "licensed_official",
      }),
    /invalid UTC cutoff input/,
  );
  assert.throws(
    () =>
      buildResearchRunRequestFromFormFields({
        securityId,
        asOfCutoff: "2026-07-23T13:45",
        operatorFocus: "",
        researchContract: "unsupported" as "personal_research",
      }),
    /invalid research contract selection/,
  );
});
