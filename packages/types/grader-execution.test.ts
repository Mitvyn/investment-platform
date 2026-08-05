import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseGraderExecution } from "./grader-execution.ts";

const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/grader_execution/v1/accepted-moonshot.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as unknown;

const catalystOverlay = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/grader_execution/v1/accepted-catalyst-overlay.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, any>;

const biotechOverlay = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/grader_execution/v1/accepted-biotech-overlay.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, any>;

const riskDilutionOverlay = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/grader_execution/v1/accepted-risk-dilution-overlay.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, any>;

const valuationOverlay = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/grader_execution/v1/accepted-valuation-overlay.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, any>;

const bundleContext = {
  evidenceBundleId: "4478d37e-95c4-545f-826c-d77257dfd4aa",
  evidenceBundleHash:
    "2d13851bd2d0b99ad5d5665506d36d181c68bd01501001f2da67fbcd6912cafe",
  evidenceIds: [
    "8d80b1a6-0742-5b0c-bf48-4e0d32cb8200",
    "3663f956-71fe-55bd-a305-5a686bffcf69",
  ],
} as const;

function specialistCandidate(overlay: Record<string, any>) {
  const candidate = structuredClone(fixture) as Record<string, any>;
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
    candidate[key] = overlay[key];
  }
  candidate.attempts[0].prompt_version = overlay.prompt_version;
  candidate.opinion.grader_id = overlay.grader_id;
  candidate.opinion.grader_version = overlay.grader_version;
  candidate.opinion.owned_decision_question = overlay.owned_decision_question;
  delete candidate.opinion.moonshot_payload;
  candidate.opinion[overlay.payload_key] = overlay.payload;
  return candidate;
}

function personalResearchCandidate() {
  const candidate = structuredClone(fixture) as Record<string, any>;
  candidate.question_type_id =
    "biotech_moonshot_catalyst_personal_research_assessment";
  candidate.question_type_version =
    "biotech_moonshot_catalyst_personal_research_assessment.v1";
  candidate.workflow_config_version =
    "biotech-moonshot-catalyst-personal-research-v1";
  candidate.thesis_contract_id =
    "biotech_moonshot_catalyst_personal_research_v1";
  return candidate;
}

function notExecutedCandidate() {
  const candidate = structuredClone(fixture) as Record<string, any>;
  candidate.execution_state = "not_executed";
  candidate.pre_call_gate.status = "blocked";
  candidate.pre_call_gate.checks[4] = {
    check_id: "budget_available",
    passed: false,
    reason_code: "insufficient_budget",
  };
  candidate.budget = {
    reservation_id: null,
    budget_policy_version: "research_budget.v1",
    currency: "USD",
    reserved_cost_usd: "0",
    reconciled_cost_usd: null,
    status: "not_reserved",
  };
  candidate.attempts = [];
  candidate.total_usage = {
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
  candidate.total_cost = {
    reserved_cost_usd: "0",
    estimated_cost_usd: "0",
    billed_cost_usd: null,
    currency: "USD",
    price_card_version: "gpt_5_6_sol_usd.v1",
  };
  candidate.not_executed = {
    reason_code: "insufficient_budget",
    reason: "Hard budget cannot reserve worst-case attempt cost.",
    gate_policy_version: "model_execution_gate.v1",
    failed_gate_checks: ["budget_available"],
  };
  candidate.failure = null;
  candidate.opinion = null;
  return candidate;
}

function abstainedCandidate() {
  const candidate = structuredClone(fixture) as Record<string, any>;
  candidate.execution_state = "abstained";
  candidate.attempts[0].result = "abstained";
  candidate.opinion.execution_state = "abstained";
  candidate.opinion.stance = null;
  candidate.opinion.proposition.grader_stance = null;
  candidate.opinion.proposition.stance_rationale = null;
  candidate.opinion.abstention = {
    reason_code: "evidence_maturity_insufficient",
    reason: "Bundle cannot support a defensible Moonshot verdict.",
    missing_or_inadequate_evidence: ["Clinical efficacy evidence"],
    evidence_required: ["Controlled clinical efficacy readout"],
    confidence: "high",
  };
  return candidate;
}

function exhaustedFailureCandidate() {
  const candidate = structuredClone(fixture) as Record<string, any>;
  const first = structuredClone(candidate.attempts[0]);
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
  second.provider_request_id = "req_failed_002";
  second.raw_payload_id = "7dfdb305-0f51-494a-a5e9-86175f3ba1cb";
  second.raw_payload_sha256 =
    "409aeb844afcb8f95824d5a79b1552c8faaf3f5b9232898691e8bdc66d777d7c";
  second.started_at = "2026-05-06T22:01:04Z";
  second.finished_at = "2026-05-06T22:01:06Z";
  second.retry_reason = null;

  candidate.execution_state = "failed";
  candidate.attempts = [first, second];
  candidate.total_usage = {
    input_tokens: 4000,
    cached_input_tokens: 1000,
    cache_write_tokens: 0,
    uncached_input_tokens: 3000,
    output_tokens: 1200,
    reasoning_tokens: 600,
    total_tokens: 5200,
    tool_call_count: 0,
    usage_complete: true,
  };
  candidate.total_cost.estimated_cost_usd = "0.011160";
  candidate.total_cost.billed_cost_usd = "0.011160";
  candidate.budget.reconciled_cost_usd = "0.011160";
  candidate.failure = {
    category: "schema_validation",
    attempt_count: 2,
    validation_errors: ["schema.required:summary"],
    final_reason: "Two attempts failed schema validation.",
    retry_policy_version: "grader_retry.v1",
  };
  candidate.opinion = null;
  return candidate;
}

test("accepts one isolated Moonshot grader execution against frozen bundle", () => {
  assert.deepEqual(parseGraderExecution(fixture, bundleContext), fixture);
});

test("accepts personal-research execution under exact separate contract identity", () => {
  const candidate = personalResearchCandidate();

  assert.deepEqual(parseGraderExecution(candidate, bundleContext), candidate);
});

test("rejects mixed strict and personal-research contract identities", () => {
  const candidate = personalResearchCandidate();
  candidate.workflow_config_version = "biotech-moonshot-catalyst-v1";

  assert.throws(
    () => parseGraderExecution(candidate, bundleContext),
    /research contract identity/,
  );
});

test("accepts one isolated Catalyst grader execution with Catalyst-owned payload", () => {
  const candidate = specialistCandidate(catalystOverlay);

  assert.deepEqual(parseGraderExecution(candidate, bundleContext), candidate);
});

test("accepts one isolated Biotech grader execution with Biotech-owned payload", () => {
  const candidate = specialistCandidate(biotechOverlay);

  assert.deepEqual(parseGraderExecution(candidate, bundleContext), candidate);
});

test("accepts one isolated Risk/Dilution grader execution with Risk/Dilution-owned payload", () => {
  const candidate = specialistCandidate(riskDilutionOverlay);

  assert.deepEqual(parseGraderExecution(candidate, bundleContext), candidate);
});

test("accepts one isolated Valuation grader execution with Valuation-owned payload", () => {
  const candidate = specialistCandidate(valuationOverlay);

  assert.deepEqual(parseGraderExecution(candidate, bundleContext), candidate);
});

test("accepts cache-write usage in attempt and execution totals", () => {
  const candidate = structuredClone(fixture) as Record<string, any>;
  candidate.attempts[0].usage.cache_write_tokens = 400;
  candidate.total_usage.cache_write_tokens = 400;

  assert.deepEqual(parseGraderExecution(candidate, bundleContext), candidate);
});

test("rejects cache writes larger than uncached input", () => {
  const candidate = structuredClone(fixture) as Record<string, any>;
  candidate.attempts[0].usage.cache_write_tokens =
    candidate.attempts[0].usage.uncached_input_tokens + 1;
  candidate.total_usage.cache_write_tokens =
    candidate.total_usage.uncached_input_tokens + 1;

  assert.throws(
    () => parseGraderExecution(candidate, bundleContext),
    /cache-write tokens/,
  );
});

test("rejects grader output under different shared proposition identity", () => {
  const candidate = structuredClone(fixture) as Record<string, any>;
  candidate.opinion.proposition.proposition_version = "replacement.v2";

  assert.throws(
    () => parseGraderExecution(candidate, bundleContext),
    /proposition identity/,
  );
});

test("rejects execution when versioned output schema differs from Moonshot payload", () => {
  const candidate = structuredClone(fixture) as Record<string, any>;
  candidate.output_schema_version = "moonshot_grader_payload.v2";

  assert.throws(
    () => parseGraderExecution(candidate, bundleContext),
    /output schema identity/,
  );
});

test("preserves blocked pre-call gate as not_executed without provider attempt or opinion", () => {
  const candidate = notExecutedCandidate();

  assert.deepEqual(parseGraderExecution(candidate, bundleContext), candidate);
});

test("not_executed reason identifies exactly failed deterministic gate checks", () => {
  const candidate = notExecutedCandidate();
  candidate.not_executed.failed_gate_checks = ["price_card_available"];

  assert.throws(
    () => parseGraderExecution(candidate, bundleContext),
    /failed gate checks/,
  );
});

test("accepts citations only from frozen bundle and excludes raw or reasoning payloads", () => {
  const outsideBundle = structuredClone(fixture) as Record<string, any>;
  outsideBundle.opinion.material_claims[0].evidence_ids = [
    "00000000-0000-4000-8000-000000000000",
  ];

  const rawResponse = structuredClone(fixture) as Record<string, any>;
  rawResponse.attempts[0].raw_response = { output: "hidden" };

  const reasoning = structuredClone(fixture) as Record<string, any>;
  reasoning.opinion.reasoning_content = "hidden chain of thought";

  for (const candidate of [outsideBundle, rawResponse, reasoning]) {
    assert.throws(() => parseGraderExecution(candidate, bundleContext), TypeError);
  }
});

test("stores valid abstention without stance and with evidence required for verdict", () => {
  const candidate = abstainedCandidate();

  assert.deepEqual(parseGraderExecution(candidate, bundleContext), candidate);

  candidate.opinion.stance = "mixed";
  assert.throws(() => parseGraderExecution(candidate, bundleContext), /abstained/);
});

test("preserves exhausted failure after exactly two pinned identical-input attempts", () => {
  const candidate = exhaustedFailureCandidate();

  assert.deepEqual(parseGraderExecution(candidate, bundleContext), candidate);

  candidate.attempts[1].request_sha256 =
    "0000000000000000000000000000000000000000000000000000000000000000";
  assert.throws(() => parseGraderExecution(candidate, bundleContext), /logical input/);
});

test("aggregate usage and decimal cost reconcile exactly to immutable attempts", () => {
  const badUsage = structuredClone(fixture) as Record<string, any>;
  badUsage.total_usage.output_tokens += 1;
  badUsage.total_usage.total_tokens += 1;

  const badCost = structuredClone(fixture) as Record<string, any>;
  badCost.total_cost.estimated_cost_usd = "0.005581";

  assert.throws(
    () => parseGraderExecution(badUsage, bundleContext),
    /total usage/,
  );
  assert.throws(
    () => parseGraderExecution(badCost, bundleContext),
    /total cost/,
  );
});

test("keeps version identities exact across execution, attempts, opinions, and failures", () => {
  const wrongThesisContract = structuredClone(fixture) as Record<string, any>;
  wrongThesisContract.thesis_contract_id = "different_contract";

  const wrongAttemptPrompt = structuredClone(fixture) as Record<string, any>;
  wrongAttemptPrompt.attempts[0].prompt_version = "moonshot_prompt.v2";

  const wrongOpinionGrader = structuredClone(fixture) as Record<string, any>;
  wrongOpinionGrader.opinion.grader_version = "moonshot.v2";

  const wrongFailurePolicy = exhaustedFailureCandidate();
  wrongFailurePolicy.failure.retry_policy_version = "grader_retry.v2";

  for (const candidate of [
    wrongThesisContract,
    wrongAttemptPrompt,
    wrongOpinionGrader,
    wrongFailurePolicy,
  ]) {
    assert.throws(() => parseGraderExecution(candidate, bundleContext), TypeError);
  }
});

test("publishes Grader Execution v1 through package root and strict JSON Schema", () => {
  const publicTypes = readFileSync(new URL("./index.ts", import.meta.url), "utf8");
  const schema = JSON.parse(
    readFileSync(
      new URL("./grader-execution.schema.json", import.meta.url),
      "utf8",
    ),
  ) as Record<string, any>;

  assert.match(publicTypes, /parseGraderExecution/);
  assert.match(publicTypes, /type GraderExecution/);
  assert.equal(schema.$schema, "https://json-schema.org/draft/2020-12/schema");
  assert.equal(schema.properties.contract_version.const, "grader_execution.v1");
  assert.deepEqual(schema.properties.execution_state.enum, [
    "not_executed",
    "failed",
    "abstained",
    "accepted",
  ]);
  assert.equal(schema.additionalProperties, false);
  assert.equal(schema.$defs.attempt.additionalProperties, false);
  assert.equal(schema.$defs.opinion.additionalProperties, false);
  assert.equal(schema.$defs.moonshot_payload.additionalProperties, false);
  assert.equal(schema.$defs.catalyst_payload.additionalProperties, false);
  assert.equal(schema.$defs.biotech_payload.additionalProperties, false);
  assert.equal(schema.$defs.risk_dilution_payload.additionalProperties, false);
  assert.equal(schema.$defs.valuation_payload.additionalProperties, false);
  assert.deepEqual(schema.properties.grader_id.enum, [
    "moonshot",
    "catalyst",
    "biotech",
    "risk_dilution",
    "valuation",
  ]);
  assert.deepEqual(
    schema.allOf[0].oneOf.map(
      (entry: Record<string, any>) =>
        Object.fromEntries(
          Object.entries(entry.properties).map(([key, value]) => [
            key,
            (value as Record<string, string>).const,
          ]),
        ),
    ),
    [
      {
        question_type_id: "biotech_moonshot_catalyst_assessment",
        question_type_version: "biotech_moonshot_catalyst_assessment.v1",
        workflow_config_version: "biotech-moonshot-catalyst-v1",
        thesis_contract_id: "biotech_moonshot_catalyst_assessment",
      },
      {
        question_type_id:
          "biotech_moonshot_catalyst_personal_research_assessment",
        question_type_version:
          "biotech_moonshot_catalyst_personal_research_assessment.v1",
        workflow_config_version:
          "biotech-moonshot-catalyst-personal-research-v1",
        thesis_contract_id:
          "biotech_moonshot_catalyst_personal_research_v1",
      },
    ],
  );
  assert.doesNotMatch(JSON.stringify(schema), /reasoning_content|raw_request|raw_response/);
});
