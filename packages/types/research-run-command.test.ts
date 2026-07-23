import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseResearchRunCommandReceipt } from "./research-run-command.ts";

const blockedReceipt = {
  contract_version: "research_run_command_receipt.v1",
  command_id: "11111111-1111-4111-8111-111111111111",
  operator_id: "027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
  security_id: "22222222-2222-4222-8222-222222222222",
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

test("accepts one blocked Research Run command without execution output", () => {
  assert.deepEqual(
    parseResearchRunCommandReceipt(blockedReceipt),
    blockedReceipt,
  );
});

test("rejects malformed or contradictory Research Run command receipts", () => {
  const invalid = [
    { ...blockedReceipt, unexpected: true },
    { ...blockedReceipt, command_id: "not-a-uuid" },
    { ...blockedReceipt, state: "blocked", blocking_reason_codes: [] },
    {
      ...blockedReceipt,
      state: "blocked",
      research_run_id: "33333333-3333-4333-8333-333333333333",
    },
    {
      ...blockedReceipt,
      state: "completed",
      blocking_reason_codes: [],
      research_run_id: null,
    },
    { ...blockedReceipt, as_of_cutoff: "2026-07-23" },
    { ...blockedReceipt, operator_focus_normalized: "  focus  " },
  ];

  for (const candidate of invalid) {
    assert.throws(
      () => parseResearchRunCommandReceipt(candidate),
      TypeError,
    );
  }
});

test("publishes Research Run command contract through package root", () => {
  const packageIndex = readFileSync(
    new URL("./index.ts", import.meta.url),
    "utf8",
  );

  assert.match(packageIndex, /parseResearchRunCommandReceipt/);
  assert.match(packageIndex, /type ResearchRunCommandReceipt/);
});

test("publishes strict versioned Research Run command JSON Schema", () => {
  const schema = JSON.parse(
    readFileSync(
      new URL("./research-run-command.schema.json", import.meta.url),
      "utf8",
    ),
  );

  assert.equal(schema.additionalProperties, false);
  assert.equal(
    schema.properties.contract_version.const,
    "research_run_command_receipt.v1",
  );
  assert.deepEqual(schema.required.sort(), Object.keys(blockedReceipt).sort());
});
