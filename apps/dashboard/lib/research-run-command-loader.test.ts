import assert from "node:assert/strict";
import test from "node:test";

import { createResearchRunCommandLoader } from "./research-run-command-loader.ts";

const operatorId = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792";
const securityId = "22222222-2222-4222-8222-222222222222";
const commandId = "11111111-1111-4111-8111-111111111111";

const row = {
  contract_version: "research_run_command_receipt.v2",
  id: commandId,
  operator_id: operatorId,
  security_id: securityId,
  question_type_version: "biotech_moonshot_catalyst_assessment.v1",
  workflow_config_version: "biotech-moonshot-catalyst-v1",
  as_of_cutoff: "2026-07-23T05:00:00+00:00",
  operator_focus_normalized: null,
  idempotency_key:
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  capture_id: "44444444-4444-4444-8444-444444444444",
  capture_revision: 3,
  capture_content_hash:
    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  command_state: "blocked",
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
};

test("loads one owner-scoped Research Run command", async () => {
  const requests: unknown[] = [];
  const loadCommand = createResearchRunCommandLoader(
    async (owner, command) => {
      requests.push([owner, command]);
      return [row];
    },
  );

  const receipt = await loadCommand(operatorId, commandId);

  assert.deepEqual(requests, [[operatorId, commandId]]);
  assert.equal(receipt?.contract_version, "research_run_command_receipt.v2");
  assert.equal(
    receipt?.contract_version === "research_run_command_receipt.v2"
      ? receipt.capture_revision
      : null,
    3,
  );
  assert.equal(receipt?.state, "blocked");
  assert.deepEqual(receipt?.blocking_reason_codes, row.blocking_reason_codes);
});

test("keeps historical rows readable and rejects partial capture identity", async () => {
  const historical = createResearchRunCommandLoader(async () => [
    {
      ...row,
      contract_version: "research_run_command_receipt.v1",
      capture_id: null,
      capture_revision: null,
      capture_content_hash: null,
    },
  ]);
  const historicalReceipt = await historical(operatorId, commandId);
  assert.equal(
    historicalReceipt?.contract_version,
    "research_run_command_receipt.v1",
  );

  const partial = createResearchRunCommandLoader(async () => [
    { ...row, capture_content_hash: null },
  ]);
  await assert.rejects(
    partial(operatorId, commandId),
    /capture identity is incomplete/,
  );

  const mislabeled = createResearchRunCommandLoader(async () => [
    { ...row, contract_version: "research_run_command_receipt.v1" },
  ]);
  await assert.rejects(
    mislabeled(operatorId, commandId),
    /capture identity contradicts contract version/,
  );
});

test("returns null for no row and rejects ambiguous or cross-owner rows", async () => {
  const empty = createResearchRunCommandLoader(async () => []);
  assert.equal(await empty(operatorId, commandId), null);

  const ambiguous = createResearchRunCommandLoader(async () => [row, row]);
  await assert.rejects(
    ambiguous(operatorId, commandId),
    /command identity is ambiguous/,
  );

  const crossOwner = createResearchRunCommandLoader(async () => [
    {
      ...row,
      operator_id: "33333333-3333-4333-8333-333333333333",
    },
  ]);
  await assert.rejects(
    crossOwner(operatorId, commandId),
    /outside requested owner scope/,
  );
});
