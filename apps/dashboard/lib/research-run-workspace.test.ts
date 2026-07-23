import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { ResearchRun } from "../../../packages/types/research-run.ts";

import {
  presentResearchRunState,
  researchRunWorkspaceFields,
  resolveResearchRunWorkspace,
} from "./research-run-workspace.ts";

const runFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/research_run/v1/eligible.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as ResearchRun;

test("unauthenticated visitors are sent to login without loading a Research Run", async () => {
  let loadCalls = 0;

  const result = await resolveResearchRunWorkspace({
    operatorId: null,
    runId: "78d9ab11-17a1-567c-a192-fb91ec9de3be",
    loadRun: async () => {
      loadCalls += 1;
      return null;
    },
  });

  assert.deepEqual(result, { kind: "redirect", location: "/login" });
  assert.equal(loadCalls, 0);
});

test("an authenticated operator cannot receive another owner's Research Run", async () => {
  const currentOperatorId = "11111111-1111-4111-8111-111111111111";
  let requestedOwner: string | null = null;

  const result = await resolveResearchRunWorkspace({
    operatorId: currentOperatorId,
    runId: runFixture.id,
    loadRun: async (operatorId) => {
      requestedOwner = operatorId;
      return runFixture;
    },
  });

  assert.equal(requestedOwner, currentOperatorId);
  assert.deepEqual(result, { kind: "not_found" });
});

test("an authenticated operator receives not found when the scoped run is absent", async () => {
  const result = await resolveResearchRunWorkspace({
    operatorId: runFixture.operator_id,
    runId: "00000000-0000-4000-8000-000000000000",
    loadRun: async () => null,
  });

  assert.deepEqual(result, { kind: "not_found" });
});

test("the workspace exposes the complete versioned Research Run audit identity", () => {
  const fields = researchRunWorkspaceFields(runFixture);
  const byLabel = Object.fromEntries(
    [...fields.identity, ...fields.contract, ...fields.audit].map((field) => [
      field.label,
      field.value,
    ]),
  );

  assert.deepEqual(byLabel, {
    "Security ID": runFixture.security_id,
    CIK: runFixture.security_identity.cik,
    "Primary listing": runFixture.security_identity.primary_listing_exchange,
    "Run ID": runFixture.id,
    "Contract version": runFixture.contract_version,
    "Question type": runFixture.question_type,
    "Question version": runFixture.question_type_version,
    Workflow: runFixture.workflow_config_version,
    "Thesis contract": runFixture.thesis_contract_id,
    Cutoff: runFixture.as_of_cutoff,
    "Idempotency key": runFixture.idempotency_key,
    Created: runFixture.created_at,
    "Run status": runFixture.status,
    "Eligibility policy": runFixture.eligibility.policy_version,
  });
});

test("semantic state presentation distinguishes eligibility and rule results", () => {
  assert.deepEqual(
    [
      presentResearchRunState(true, "eligibility"),
      presentResearchRunState(false, "eligibility"),
      presentResearchRunState(true, "check"),
      presentResearchRunState(false, "check"),
    ],
    [
      { label: "Eligible", variant: "verified" },
      { label: "Not eligible", variant: "destructive" },
      { label: "Pass", variant: "verified" },
      { label: "Fail", variant: "destructive" },
    ],
  );
});
