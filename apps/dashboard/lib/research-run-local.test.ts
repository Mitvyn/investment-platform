import assert from "node:assert/strict";
import test from "node:test";

import {
  enqueueLocalResearchRunCommand,
  loadLocalResearchRunCommand,
  loadLocalResearchRunCommandProgress,
} from "./research-run-local.ts";

const operatorId = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792";
const securityId = "22222222-2222-4222-8222-222222222222";
const commandId = "11111111-1111-4111-8111-111111111111";
const captureId = "44444444-4444-4444-8444-444444444444";
const hash = "b".repeat(64);
const idempotencyKey = "a".repeat(64);
const updatedAt = "2026-05-07T04:00:00.000Z";

const receipt = {
  contract_version: "research_run_local_command_receipt.v1",
  command_id: commandId,
  operator_id: operatorId,
  security_id: securityId,
  question_type_version: "biotech_moonshot_catalyst_personal_research_assessment.v1",
  workflow_config_version: "biotech-moonshot-catalyst-personal-research-v1",
  as_of_cutoff: "2026-05-06T23:59:59.000Z",
  operator_focus_normalized: null,
  idempotency_key: idempotencyKey,
  command_state: "blocked",
  blocking_reason_codes: ["approved_valuation_source_activation"],
  error_code: null,
  research_run_id: "55555555-5555-4555-8555-555555555555",
  created_at: updatedAt,
  updated_at: updatedAt,
  started_at: updatedAt,
  finished_at: updatedAt,
  capture_id: captureId,
  capture_revision: 1,
  capture_content_hash: hash,
};

const progress = {
  contract_version: "research_run_local_command_progress.v1",
  operator_id: operatorId,
  command_id: commandId,
  command_state: "blocked",
  attempt_id: "66666666-6666-4666-8666-666666666666",
  attempt_number: 1,
  attempt_state: "failed",
  active_stage: null,
  completed_stages: ["research_run", "evidence_bundle"],
  lease_started_at: updatedAt,
  lease_expires_at: "2026-05-07T04:05:00.000Z",
  failure_stage: "valuation_snapshot",
  error_code: "approved_valuation_source_activation",
  retryable: false,
  updated_at: updatedAt,
};

const environment = {
  IROS_DESKTOP: "1",
  IROS_DESKTOP_CONTROL_ORIGIN: "http://127.0.0.1:61555",
  IROS_DESKTOP_CONTROL_TOKEN: "x".repeat(43),
  IROS_DESKTOP_WORKER_STATE: "ready",
};

function response(value: unknown, ok = true): Response {
  return {
    ok,
    json: async () => value,
  } as Response;
}

test("local enqueue sends server-owned capture identity to desktop worker", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const result = await enqueueLocalResearchRunCommand(
    {
      operatorId,
      securityId,
      ticker: "FRVO",
      request: {
        question_type: "biotech_moonshot_catalyst_personal_research_assessment",
        security_id: securityId,
        as_of_cutoff: "2026-05-06T23:59:59.000Z",
        workflow_config_version:
          "biotech-moonshot-catalyst-personal-research-v1",
        operator_focus: "",
      },
      preparedCapture: {
        capture_id: captureId,
        capture_revision: 1,
        capture_content_hash: hash,
      },
      now: new Date("2026-05-07T04:00:00.000Z"),
    },
    environment,
    async (input, init) => {
      requests.push({ url: String(input), init });
      return response({
        contract_version: "research_run_local_command_response.v1",
        receipt,
        progress,
      });
    },
  );

  assert.equal(result.receipt.contract_version, "research_run_local_command_receipt.v1");
  assert.equal(result.receipt.state, "blocked");
  assert.deepEqual(result.progress.completed_stages, ["research_run", "evidence_bundle"]);
  assert.equal(requests[0].url, `${environment.IROS_DESKTOP_CONTROL_ORIGIN}/v1/research/run/command`);
  assert.equal(requests[0].init?.headers instanceof Headers, false);
  assert.match(String((requests[0].init?.headers as Record<string, string>).Authorization), /^Bearer /);
  assert.equal(JSON.parse(String(requests[0].init?.body)).ticker, "FRVO");
  assert.equal(JSON.parse(String(requests[0].init?.body)).capture_content_hash, hash);
});

test("local command loader parses local receipt and progress without hosted-contract substitution", async () => {
  const calls: string[] = [];
  const fetcher = async (input: string | URL | Request) => {
    calls.push(String(input));
    return response({
      contract_version: "research_run_local_command_response.v1",
      receipt,
      progress,
    });
  };

  const loaded = await loadLocalResearchRunCommand(operatorId, commandId, environment, fetcher);
  const loadedProgress = await loadLocalResearchRunCommandProgress(
    operatorId,
    commandId,
    environment,
    fetcher,
  );

  assert.equal(loaded?.contract_version, "research_run_local_command_receipt.v1");
  assert.equal(loaded?.state, "blocked");
  assert.deepEqual(loadedProgress?.completed_stages, progress.completed_stages);
  assert.equal(loadedProgress?.contract_version, "research_run_command_progress.v1");
  assert.equal(calls.length, 2);
  assert.match(calls[1], /operator_id=/);
  assert.match(calls[1], /command_id=/);
});

test("local adapter fails closed outside desktop runtime", async () => {
  await assert.rejects(
    enqueueLocalResearchRunCommand(
      {
        operatorId,
        securityId,
        ticker: "FRVO",
        request: {
          question_type: "biotech_moonshot_catalyst_personal_research_assessment",
          security_id: securityId,
          as_of_cutoff: "2026-05-06T23:59:59.000Z",
          workflow_config_version:
            "biotech-moonshot-catalyst-personal-research-v1",
          operator_focus: "",
        },
        preparedCapture: {
          capture_id: captureId,
          capture_revision: 1,
          capture_content_hash: hash,
        },
        now: new Date("2026-05-07T04:00:00.000Z"),
      },
      {},
      async () => response({}),
    ),
    /desktop worker unavailable/,
  );
});

test("local adapter rejects malformed local progress state", async () => {
  await assert.rejects(
    loadLocalResearchRunCommandProgress(
      operatorId,
      commandId,
      environment,
      async () =>
        response({
          contract_version: "research_run_local_command_response.v1",
          receipt,
          progress: { ...progress, command_state: "not-a-state" },
        }),
    ),
    /invalid local Research Run progress/,
  );
});

test("local adapter rejects non-string or mismatched research contract versions", async () => {
  await assert.rejects(
    loadLocalResearchRunCommand(
      operatorId,
      commandId,
      environment,
      async () =>
        response({
          contract_version: "research_run_local_command_response.v1",
          receipt: {
            ...receipt,
            question_type_version: 42,
            workflow_config_version: "different-workflow.v1",
          },
          progress,
        }),
    ),
    /invalid local Research Run receipt/,
  );
});
