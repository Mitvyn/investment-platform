import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type {
  EvidenceBundle,
  GraderExecution,
  ResearchRun,
} from "@iros/types";

import { presentGraderExecutionWorkspace } from "./grader-execution-workspace.ts";

const runFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/research_run/v1/eligible.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as ResearchRun;

const bundleFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/evidence_bundle/v1/grader-ready.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as EvidenceBundle;

const executionFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/grader_execution/v1/accepted-moonshot.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as GraderExecution;

const specialistOverlays = [
  ["Catalyst rubric result", "accepted-catalyst-overlay.json"],
  ["Biotech rubric result", "accepted-biotech-overlay.json"],
  ["Risk/Dilution rubric result", "accepted-risk-dilution-overlay.json"],
  ["Valuation rubric result", "accepted-valuation-overlay.json"],
] as const;

function specialistExecution(fixtureName: string) {
  const overlay = JSON.parse(
    readFileSync(
      new URL(
        `../../../tests/fixtures/contracts/grader_execution/v1/${fixtureName}`,
        import.meta.url,
      ),
      "utf8",
    ),
  ) as Record<string, any>;
  const execution = structuredClone(executionFixture) as Record<string, any>;
  for (const key of [
    "grader_id",
    "grader_version",
    "grader_contract_version",
    "eligibility_rule_version",
    "rubric_version",
    "output_schema_version",
    "abstention_rules_version",
    "prompt_version",
  ]) {
    execution[key] = overlay[key];
  }
  execution.opinion.grader_id = overlay.grader_id;
  execution.opinion.grader_version = overlay.grader_version;
  execution.opinion.owned_decision_question = overlay.owned_decision_question;
  delete execution.opinion.moonshot_payload;
  execution.opinion[overlay.payload_key] = overlay.payload;
  return execution as GraderExecution;
}

function alignedContext() {
  const run = structuredClone(runFixture);
  run.id = executionFixture.research_run_id;
  run.operator_id = executionFixture.operator_id;

  const bundle = structuredClone(bundleFixture);
  bundle.id = executionFixture.evidence_bundle_id;
  bundle.operator_id = executionFixture.operator_id;
  bundle.research_run_id = executionFixture.research_run_id;
  bundle.bundle_hash = executionFixture.evidence_bundle_hash;

  return { run, bundle };
}

function personalAlignedContext() {
  const { run, bundle } = alignedContext();
  const personalRun = structuredClone(run) as Record<string, any>;
  personalRun.question_type =
    "biotech_moonshot_catalyst_personal_research_assessment";
  personalRun.question_type_version =
    "biotech_moonshot_catalyst_personal_research_assessment.v1";
  personalRun.workflow_config_version =
    "biotech-moonshot-catalyst-personal-research-v1";
  personalRun.thesis_contract_id =
    "biotech_moonshot_catalyst_personal_research_v1";

  const execution = structuredClone(executionFixture) as Record<string, any>;
  execution.question_type_id = personalRun.question_type;
  execution.question_type_version = personalRun.question_type_version;
  execution.workflow_config_version = personalRun.workflow_config_version;
  execution.thesis_contract_id = personalRun.thesis_contract_id;
  return {
    run: personalRun as ResearchRun,
    bundle,
    execution: execution as GraderExecution,
  };
}

function notExecutedExecution() {
  const execution = structuredClone(executionFixture);
  execution.execution_state = "not_executed";
  execution.pre_call_gate.status = "blocked";
  execution.pre_call_gate.checks[4] = {
    check_id: "budget_available",
    passed: false,
    reason_code: "insufficient_budget",
  };
  execution.budget = {
    reservation_id: null,
    budget_policy_version: "research_budget.v1",
    currency: "USD",
    reserved_cost_usd: "0",
    reconciled_cost_usd: null,
    status: "not_reserved",
  };
  execution.attempts = [];
  execution.total_usage = {
    input_tokens: 0,
    cached_input_tokens: 0,
    cache_write_tokens: 0,
    uncached_input_tokens: 0,
    output_tokens: 0,
    reasoning_tokens: 0,
    total_tokens: 0,
    tool_call_count: 0,
    usage_complete: true,
  };
  execution.total_cost = {
    reserved_cost_usd: "0",
    estimated_cost_usd: "0",
    billed_cost_usd: null,
    currency: "USD",
    price_card_version: "gpt_5_6_sol_usd.v1",
  };
  execution.not_executed = {
    reason_code: "insufficient_budget",
    reason: "Hard budget cannot reserve worst-case attempt cost.",
    gate_policy_version: "model_execution_gate.v1",
    failed_gate_checks: ["budget_available"],
  };
  execution.failure = null;
  execution.opinion = null;
  return execution;
}

function abstainedExecution() {
  const execution = structuredClone(executionFixture);
  execution.execution_state = "abstained";
  execution.attempts[0].result = "abstained";
  if (execution.opinion === null) throw new Error("fixture opinion missing");
  execution.opinion.execution_state = "abstained";
  execution.opinion.stance = null;
  execution.opinion.proposition.grader_stance = null;
  execution.opinion.proposition.stance_rationale = null;
  execution.opinion.abstention = {
    reason_code: "evidence_maturity_insufficient",
    reason: "Bundle cannot support a defensible Moonshot verdict.",
    missing_or_inadequate_evidence: ["Clinical efficacy evidence"],
    evidence_required: ["Controlled clinical efficacy readout"],
    confidence: "high",
  };
  return execution;
}

function failedExecution() {
  const execution = structuredClone(executionFixture);
  const first = structuredClone(execution.attempts[0]);
  first.result = "validation_error";
  first.validation = {
    status: "failed",
    schema_valid: false,
    citations_valid: null,
    errors: ["schema.required:summary"],
  };
  first.retry_reason = "schema_validation_failed";

  const second = structuredClone(first);
  second.attempt_id = "49cd399f-efdb-4382-9098-01a6dfa647a9";
  second.attempt_number = 2;
  second.started_at = "2026-05-06T22:01:04Z";
  second.finished_at = "2026-05-06T22:01:06Z";
  second.retry_reason = null;

  execution.execution_state = "failed";
  execution.attempts = [first, second];
  execution.failure = {
    category: "schema_validation",
    attempt_count: 2,
    validation_errors: ["schema.required:summary"],
    final_reason: "Two attempts failed schema validation.",
    retry_policy_version: "grader_retry.v1",
  };
  execution.not_executed = null;
  execution.opinion = null;
  return execution;
}

test("accepted grader execution exposes validated opinion and auditable model cost", () => {
  const { run, bundle } = alignedContext();
  const presentation = presentGraderExecutionWorkspace(run, bundle, [
    executionFixture,
  ]);

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  const execution = presentation.executions[0];
  assert.deepEqual(execution.status, {
    label: "Accepted",
    variant: "verified",
  });
  assert.equal(execution.configuration.provider, "openai");
  assert.equal(execution.configuration.model, "gpt-5.6-sol");
  assert.equal(execution.usage.totalTokens, "2,600");
  assert.equal(execution.usage.reasoningTokens, "300");
  assert.equal(execution.cost.estimated, "USD 0.005580");
  assert.equal(execution.attempts[0].validation.label, "Validated");
  assert.equal(execution.attempts[0].rawOutputState, "Stored in restricted audit record");
  assert.equal(execution.opinion?.stance.label, "Supports");
  assert.deepEqual(execution.opinion?.claims[0].evidenceIds, [
    "8d80b1a6-0742-5b0c-bf48-4e0d32cb8200",
  ]);
  assert.doesNotMatch(
    JSON.stringify(presentation),
    /raw_payload_id|raw_payload_sha256|raw_request|raw_response|reasoning_content/,
  );
});

test("personal-research grader execution displays only under matching run contract", () => {
  const { run, bundle, execution } = personalAlignedContext();

  const presentation = presentGraderExecutionWorkspace(run, bundle, [execution]);

  assert.equal(presentation.kind, "ready");
  assert.throws(
    () => presentGraderExecutionWorkspace(run, bundle, [executionFixture]),
    /research contract boundary/,
  );
});

test("missing frozen bundle blocks grader audit loading explicitly", () => {
  const { run } = alignedContext();

  assert.deepEqual(presentGraderExecutionWorkspace(run, null, []), {
    kind: "missing",
    description:
      "Frozen Evidence Bundle must exist before grader executions can be audited.",
    status: { label: "Not available", variant: "attention" },
  });
});

test("accepted execution exposes complete permitted audit metadata without provider body", () => {
  const { run, bundle } = alignedContext();
  const presentation = presentGraderExecutionWorkspace(run, bundle, [
    executionFixture,
  ]);

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  const execution = presentation.executions[0];
  assert.equal(execution.identity.id, executionFixture.id);
  assert.equal(execution.identity.executionKey, executionFixture.execution_key);
  assert.equal(execution.identity.bundleHash, executionFixture.evidence_bundle_hash);
  assert.equal(execution.configuration.rubric, "moonshot_rubric.v1");
  assert.equal(execution.configuration.outputSchema, "moonshot_grader_payload.v1");
  assert.deepEqual(execution.gate.status, {
    label: "Passed",
    variant: "verified",
  });
  assert.deepEqual(execution.gate.checks[0], {
    id: "config_approved",
    label: "Config approved",
    passed: true,
    reason: "approved",
    status: { label: "Pass", variant: "verified" },
  });
  assert.equal(execution.budget.status, "reconciled");
  assert.equal(execution.budget.policy, "research_budget.v1");
  assert.equal(
    execution.attempts[0].requestHash,
    executionFixture.attempts[0].request_sha256,
  );
  assert.equal(execution.attempts[0].duration, "2,000 ms");
  assert.equal(execution.attempts[0].usage.inputTokens, "2,000");
  assert.equal(execution.attempts[0].cost.estimated, "USD 0.005580");
  assert.equal(execution.attempts[0].validation.schema, "Pass");
  assert.equal(execution.attempts[0].validation.citations, "Pass");
  assert.equal(
    execution.opinion?.ownedQuestion,
    "Is the opportunity meaningfully asymmetric?",
  );
  assert.equal(
    execution.opinion?.proposition.rationale,
    "Asymmetric platform potential and defined clinical catalyst support continued research.",
  );
  assert.deepEqual(execution.opinion?.assumptions, [
    "Clinical translation remains possible but unproven.",
  ]);
  assert.equal(execution.opinion?.contradictions[0].evidenceId, "3663f956-71fe-55bd-a305-5a686bffcf69");
  assert.equal(execution.opinion?.gaps[0].requiredEvidence, "Clinically meaningful efficacy results.");
  assert.deepEqual(execution.opinion?.domain.fields[1], {
    label: "Asymmetry",
    value: "Credible",
  });
});

test("every specialist execution exposes its owned payload without universal scoring", () => {
  const { run, bundle } = alignedContext();

  for (const [expectedTitle, fixtureName] of specialistOverlays) {
    const presentation = presentGraderExecutionWorkspace(run, bundle, [
      specialistExecution(fixtureName),
    ]);
    assert.equal(presentation.kind, "ready");
    if (presentation.kind !== "ready") continue;
    assert.equal(presentation.executions[0].opinion?.domain.title, expectedTitle);
    assert.ok(presentation.executions[0].opinion?.domain.fields.length);
    assert.doesNotMatch(
      JSON.stringify(presentation.executions[0].opinion?.domain),
      /universal.?score|weighted.?score|grade/i,
    );
  }
});

test("blocked pre-call gate stays not executed and exposes exact reasons", () => {
  const { run, bundle } = alignedContext();
  const presentation = presentGraderExecutionWorkspace(run, bundle, [
    notExecutedExecution(),
  ]);

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  const execution = presentation.executions[0];
  assert.deepEqual(execution.status, {
    label: "Not executed",
    variant: "attention",
  });
  assert.deepEqual(execution.outcome, {
    kind: "not_executed",
    reasonCode: "insufficient_budget",
    reason: "Hard budget cannot reserve worst-case attempt cost.",
    policy: "model_execution_gate.v1",
    failedChecks: ["budget_available"],
  });
  assert.deepEqual(execution.attempts, []);
  assert.equal(execution.opinion, null);
});

test("valid abstention has no stance and names evidence required for verdict", () => {
  const { run, bundle } = alignedContext();
  const presentation = presentGraderExecutionWorkspace(run, bundle, [
    abstainedExecution(),
  ]);

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  const execution = presentation.executions[0];
  assert.deepEqual(execution.status, {
    label: "Abstained",
    variant: "attention",
  });
  assert.deepEqual(execution.opinion?.stance, {
    label: "No stance",
    variant: "attention",
  });
  assert.deepEqual(execution.opinion?.abstention, {
    reasonCode: "evidence_maturity_insufficient",
    reason: "Bundle cannot support a defensible Moonshot verdict.",
    missingEvidence: ["Clinical efficacy evidence"],
    evidenceRequired: ["Controlled clinical efficacy readout"],
    confidence: "high",
  });
});

test("exhausted failure exposes bounded retry chronology and no opinion", () => {
  const { run, bundle } = alignedContext();
  const presentation = presentGraderExecutionWorkspace(run, bundle, [
    failedExecution(),
  ]);

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  const execution = presentation.executions[0];
  assert.deepEqual(execution.status, {
    label: "Failed",
    variant: "destructive",
  });
  assert.deepEqual(execution.outcome, {
    kind: "failed",
    category: "schema_validation",
    attemptCount: 2,
    validationErrors: ["schema.required:summary"],
    finalReason: "Two attempts failed schema validation.",
    retryPolicy: "grader_retry.v1",
  });
  assert.equal(execution.attempts.length, 2);
  assert.equal(execution.attempts[0].retryReason, "schema_validation_failed");
  assert.deepEqual(execution.attempts[0].validation.errors, [
    "schema.required:summary",
  ]);
  assert.equal(execution.attempts[1].number, 2);
  assert.equal(execution.opinion, null);
});

test("workspace rejects execution outside frozen Research Run boundary", () => {
  const { run, bundle } = alignedContext();
  const wrongBundle = structuredClone(executionFixture);
  wrongBundle.evidence_bundle_hash = "a".repeat(64);

  assert.throws(
    () => presentGraderExecutionWorkspace(run, bundle, [wrongBundle]),
    /outside Research Run or frozen bundle boundary/,
  );
});
