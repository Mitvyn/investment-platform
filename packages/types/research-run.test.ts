import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  mapResearchRunRows,
  normalizeResearchQuestionRequest,
  parseResearchQuestionRequest,
  parseResearchRun,
} from "./research-run.ts";

const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/research_run/v1/eligible.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as unknown;

function loadFixture(name: string): unknown {
  return JSON.parse(
    readFileSync(
      new URL(
        `../../tests/fixtures/contracts/research_run/v1/${name}`,
        import.meta.url,
      ),
      "utf8",
    ),
  );
}

test("TypeScript accepts canonical eligible Research Run without semantic drift", () => {
  assert.deepEqual(parseResearchRun(fixture), fixture);
});

test("TypeScript rejects malformed or incompatible Research Run contracts", () => {
  const valid = fixture as Record<string, unknown>;
  const { id: _removed, ...missingId } = valid;
  const invalid = [
    { ...valid, target_price: 100 },
    missingId,
    { ...valid, workflow_config_version: "biotech-moonshot-catalyst-v0" },
  ];

  for (const candidate of invalid) {
    assert.throws(() => parseResearchRun(candidate), TypeError);
  }
});

test("TypeScript rejects incomplete, reordered, or inconsistent eligibility", () => {
  const valid = fixture as Record<string, unknown>;
  const candidate = () => structuredClone(valid) as Record<string, any>;

  const missingRule = candidate();
  missingRule.eligibility.checks.pop();

  const reorderedRules = candidate();
  [reorderedRules.eligibility.checks[0], reorderedRules.eligibility.checks[1]] = [
    reorderedRules.eligibility.checks[1],
    reorderedRules.eligibility.checks[0],
  ];

  const duplicateRule = candidate();
  duplicateRule.eligibility.checks[1] = structuredClone(
    duplicateRule.eligibility.checks[0],
  );

  const unknownRule = candidate();
  unknownRule.eligibility.checks[0].rule_id = "ticker_allowlist";
  unknownRule.eligibility.checks[0].rule_version = "ticker_allowlist.v1";

  const wrongRuleVersion = candidate();
  wrongRuleVersion.eligibility.checks[0].rule_version =
    "security_identity_verified.v2";

  const falseDespiteAllPassing = candidate();
  falseDespiteAllPassing.eligibility.eligible = false;

  const trueDespiteFailedCheck = candidate();
  trueDespiteFailedCheck.eligibility.checks[0].passed = false;

  for (const [label, invalid] of Object.entries({
    missingRule,
    reorderedRules,
    duplicateRule,
    unknownRule,
    wrongRuleVersion,
    falseDespiteAllPassing,
    trueDespiteFailedCheck,
  })) {
    assert.throws(
      () => parseResearchRun(invalid),
      TypeError,
      `${label} must fail closed`,
    );
  }
});

test("TypeScript preserves unverified identity snapshots for ineligible runs", () => {
  const run = structuredClone(fixture) as Record<string, any>;
  run.security_identity.cik = "unverified";
  run.security_identity.primary_listing_exchange = "";
  run.eligibility.eligible = false;
  run.eligibility.checks[0].passed = false;
  run.eligibility.checks[0].reason_code = "security_identity_unverified";

  assert.deepEqual(parseResearchRun(run), run);
});

test("TypeScript round trips question and normalized request fixtures", () => {
  const requestFixture = loadFixture("request.json");
  const normalizedFixture = loadFixture("normalized-request.json");

  const request = parseResearchQuestionRequest(requestFixture);

  assert.deepEqual(request, requestFixture);
  assert.deepEqual(normalizeResearchQuestionRequest(request), normalizedFixture);
});

test("TypeScript routes personal research into a separate thesis contract", () => {
  const strictRequest = loadFixture("request.json") as Record<string, unknown>;
  const personalRequest = parseResearchQuestionRequest({
    ...strictRequest,
    question_type:
      "biotech_moonshot_catalyst_personal_research_assessment",
    workflow_config_version:
      "biotech-moonshot-catalyst-personal-research-v1",
  });

  assert.deepEqual(normalizeResearchQuestionRequest(personalRequest), {
    question_type:
      "biotech_moonshot_catalyst_personal_research_assessment",
    question_type_version:
      "biotech_moonshot_catalyst_personal_research_assessment.v1",
    security_id: strictRequest.security_id,
    as_of_cutoff: strictRequest.as_of_cutoff,
    workflow_config_version:
      "biotech-moonshot-catalyst-personal-research-v1",
    thesis_contract_id:
      "biotech_moonshot_catalyst_personal_research_v1",
    operator_focus_original: strictRequest.operator_focus,
    operator_focus_normalized: "Review financing through catalyst.",
  });

  const personalRun = structuredClone(fixture) as Record<string, unknown>;
  personalRun.question_type = personalRequest.question_type;
  personalRun.question_type_version =
    "biotech_moonshot_catalyst_personal_research_assessment.v1";
  personalRun.workflow_config_version = personalRequest.workflow_config_version;
  personalRun.thesis_contract_id =
    "biotech_moonshot_catalyst_personal_research_v1";
  assert.deepEqual(parseResearchRun(personalRun), personalRun);
});

test("TypeScript normalizes request identity and cutoff to canonical wire values", () => {
  const requestFixture = loadFixture("request.json") as Record<string, unknown>;
  const request = parseResearchQuestionRequest({
    ...requestFixture,
    security_id: String(requestFixture.security_id).toUpperCase(),
    as_of_cutoff: "2026-05-07T07:59:59+08:00",
  });

  const normalized = normalizeResearchQuestionRequest(request);

  assert.equal(request.security_id, requestFixture.security_id);
  assert.equal(request.as_of_cutoff, "2026-05-06T23:59:59+00:00");
  assert.equal(normalized.security_id, requestFixture.security_id);
  assert.equal(normalized.as_of_cutoff, "2026-05-06T23:59:59+00:00");
});

test("TypeScript question request fails closed", () => {
  const valid = loadFixture("request.json") as Record<string, unknown>;
  const { security_id: _removed, ...missingSecurity } = valid;
  const invalid = [
    { ...valid, readiness_override: true },
    missingSecurity,
    { ...valid, question_type: "compounder_quality_reset_assessment" },
    { ...valid, workflow_config_version: "biotech-moonshot-catalyst-v0" },
    { ...valid, as_of_cutoff: "2026-05-06" },
  ];
  for (const candidate of invalid) {
    assert.throws(() => parseResearchQuestionRequest(candidate), TypeError);
  }

  assert.throws(
    () =>
      normalizeResearchQuestionRequest(
        parseResearchQuestionRequest({
          ...valid,
          operator_focus: "Remove the valuation grader.",
        }),
      ),
    /cannot alter workflow behavior/,
  );
  assert.throws(
    () =>
      normalizeResearchQuestionRequest(
        parseResearchQuestionRequest({
          ...valid,
          operator_focus: " ".repeat(2_001),
        }),
      ),
    /exceeds 2000/,
  );
});

test("TypeScript maps owner view rows into canonical Research Run", () => {
  const run = parseResearchRun(fixture);
  const rows = run.eligibility.checks.map(
    (check, index) => ({
      operator_id: run.operator_id,
      research_run_id: run.id,
      security_id: run.security_id,
      security_identity_snapshot: run.security_identity,
      question_type: run.question_type,
      question_type_version_id: run.question_type_version,
      workflow_config_version_id: run.workflow_config_version,
      thesis_contract_id: run.thesis_contract_id,
      as_of_cutoff: run.as_of_cutoff,
      operator_focus_original: run.operator_focus_original,
      operator_focus_normalized: run.operator_focus_normalized,
      status: run.status,
      idempotency_key: run.idempotency_key,
      created_at: run.created_at,
      eligibility_policy_version: run.eligibility.policy_version,
      eligible: run.eligibility.eligible,
      evaluated_at: run.eligibility.evaluated_at,
      check_ordinal: index + 1,
      rule_id: check.rule_id,
      rule_version: check.rule_version,
      passed: check.passed,
      evidence_reference: check.evidence_reference,
      reason_code: check.reason_code,
      explanation: check.explanation,
      check_evaluated_at: check.evaluated_at,
    }),
  );

  assert.deepEqual(mapResearchRunRows(rows), fixture);
});
