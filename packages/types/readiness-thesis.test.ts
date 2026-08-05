import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  parseReadinessGateResult,
  parseThesisCreationResult,
  parseThesisChain,
  parseThesisVersion,
} from "./readiness-thesis.ts";

const readiness = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/readiness_thesis/v1/decision-ready.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, unknown>;

const canonicalThesis = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/readiness_thesis/v1/canonical-thesis.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, unknown>;

const upstream = {
  operatorId: "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735",
  securityId: "f594edb2-7fff-4e40-9c26-2c06bcbecb91",
  thesisContractId: "biotech_moonshot_catalyst_assessment",
  researchRunId: "33000000-0000-4000-8000-000000000001",
  evidenceBundleId: "4478d37e-95c4-545f-826c-d77257dfd4aa",
  evidenceBundleHash:
    "2d13851bd2d0b99ad5d5665506d36d181c68bd01501001f2da67fbcd6912cafe",
  validatedGraderOpinionIds: [
    "20000000-0000-4000-8000-000000000001",
    "20000000-0000-4000-8000-000000000002",
    "20000000-0000-4000-8000-000000000003",
    "20000000-0000-4000-8000-000000000004",
    "20000000-0000-4000-8000-000000000005",
  ],
  committeeResultId: "32000000-0000-4000-8000-000000000001",
  committeeMemoId: "30000000-0000-4000-8000-000000000001",
  committeeStatus: "complete",
  requestedDisposition: "decision_ready",
} as const;

test("accepts deterministic readiness only when every required condition passes", () => {
  assert.deepEqual(parseReadinessGateResult(readiness, upstream), readiness);
});

test("personal research readiness and thesis use separate contract identity", () => {
  const personalReadiness = structuredClone(readiness) as Record<string, any>;
  personalReadiness.thesis_contract_id =
    "biotech_moonshot_catalyst_personal_research_v1";
  personalReadiness.gate_policy_version = "biotech-personal-readiness.v1";
  personalReadiness.passed_checks = personalReadiness.passed_checks.map(
    (check: Record<string, any>) => ({
      ...check,
      check_version: "biotech-personal-readiness.v1",
    }),
  );
  const personalContext = {
    ...upstream,
    thesisContractId:
      "biotech_moonshot_catalyst_personal_research_v1",
  } as const;
  const parsedReadiness = parseReadinessGateResult(
    personalReadiness,
    personalContext,
  );
  const personalThesis = structuredClone(canonicalThesis) as Record<string, any>;
  personalThesis.thesis_contract_id = personalContext.thesisContractId;
  personalThesis.question_type_version =
    "biotech_moonshot_catalyst_personal_research_assessment.v1";
  personalThesis.workflow_config_version =
    "biotech-moonshot-catalyst-personal-research-v1";
  personalThesis.readiness_gate_policy_version =
    "biotech-personal-readiness.v1";

  const parsedThesis = parseThesisVersion(personalThesis, {
    readinessResult: parsedReadiness,
    questionTypeVersion:
      "biotech_moonshot_catalyst_personal_research_assessment.v1",
    workflowConfigVersion:
      "biotech-moonshot-catalyst-personal-research-v1",
    propositionId: "biotech_moonshot_catalyst_case",
    propositionVersion: "biotech_moonshot_catalyst_case.v1",
    memoStatementIds: [
      "statement-common-ground",
      "statement-invalidation",
      "statement-gap",
      "statement-review-trigger",
    ],
    memoDisagreementIds: ["disagreement-financing-asymmetry"],
  });

  assert.equal(
    parsedThesis.thesis_contract_id,
    "biotech_moonshot_catalyst_personal_research_v1",
  );
  assert.throws(
    () =>
      parseReadinessGateResult(
        {
          ...personalReadiness,
          gate_policy_version: "biotech-readiness.v1",
        },
        personalContext,
      ),
    /gate policy identity mismatch/,
  );
});

function blockedDecisionReady(): Record<string, any> {
  const blocked = structuredClone(readiness) as Record<string, any>;
  const failed = blocked.passed_checks.pop();
  failed.reason_code = "missing_review_trigger";
  failed.explanation = "Required review trigger is absent.";
  blocked.failed_checks = [failed];
  blocked.blocking_reasons = [{
    reason_code: "missing_review_trigger",
    check_id: "thesis_required_contents_present",
    explanation: "A thesis cannot be decision-ready without a review trigger.",
  }];
  blocked.required_next_evidence = [{
    requirement_id: "review-trigger",
    description: "Add a source-backed review trigger.",
    affected_check_ids: ["thesis_required_contents_present"],
  }];
  blocked.final_disposition = "deep_research";
  blocked.readiness_status = "blocked";
  return blocked;
}

function parseCanonicalThesis() {
  return parseThesisVersion(canonicalThesis, {
    readinessResult: parseReadinessGateResult(readiness, upstream),
    questionTypeVersion: "biotech_moonshot_catalyst_assessment.v1",
    workflowConfigVersion: "biotech-moonshot-catalyst-v1",
    propositionId: "biotech_moonshot_catalyst_case",
    propositionVersion: "biotech_moonshot_catalyst_case.v1",
    memoStatementIds: [
      "statement-common-ground",
      "statement-invalidation",
      "statement-gap",
      "statement-review-trigger",
    ],
    memoDisagreementIds: ["disagreement-financing-asymmetry"],
  });
}

test("downgrades a requested decision_ready result when one condition fails", () => {
  const blocked = blockedDecisionReady();
  assert.deepEqual(parseReadinessGateResult(blocked, upstream), blocked);
});

test("never upgrades a disposition or preserves decision_ready over a failed check", () => {
  const upgraded = structuredClone(readiness) as Record<string, any>;
  upgraded.requested_disposition = "monitor";
  upgraded.final_disposition = "decision_ready";
  upgraded.readiness_status = "passed";
  const monitorContext = {...upstream, requestedDisposition: "monitor"} as const;

  const bypassed = blockedDecisionReady();
  bypassed.final_disposition = "decision_ready";
  bypassed.readiness_status = "passed";

  assert.throws(
    () => parseReadinessGateResult(upgraded, monitorContext),
    /cannot upgrade disposition|invalid non-requested readiness result/,
  );
  assert.throws(
    () => parseReadinessGateResult(bypassed, upstream),
    /decision_ready requires every readiness check/,
  );
});

test("rejects scores, votes, confidence, sentiment, enthusiasm, actions, and sizing as gate inputs", () => {
  for (const field of [
    "score",
    "vote_result",
    "average_confidence",
    "market_sentiment",
    "operator_enthusiasm",
    "trade_action",
    "position_size",
  ]) {
    const bypass = structuredClone(readiness) as Record<string, unknown>;
    bypass[field] = "prohibited";
    assert.throws(
      () => parseReadinessGateResult(bypass, upstream),
      /invalid readiness gate result fields/,
    );
  }
});

test("accepts an immutable canonical thesis tied to the exact complete run", () => {
  assert.deepEqual(parseCanonicalThesis(), canonicalThesis);
});

test("creates a non-superseding provisional thesis from a committee with abstentions", () => {
  const provisionalReadiness = blockedDecisionReady();
  provisionalReadiness.committee_status = "complete_with_abstentions";
  const provisionalContext = {
    ...upstream,
    committeeStatus: "complete_with_abstentions",
  } as const;
  const parsedReadiness = parseReadinessGateResult(
    provisionalReadiness,
    provisionalContext,
  );
  const provisional = structuredClone(canonicalThesis) as Record<string, any>;
  provisional.thesis_version_id = "41000000-0000-4000-8000-000000000002";
  provisional.thesis_status = "provisional";
  provisional.previous_canonical_thesis_version_id =
    "41000000-0000-4000-8000-000000000001";
  provisional.based_on_thesis_version_id =
    "41000000-0000-4000-8000-000000000001";
  provisional.committee_status = "complete_with_abstentions";
  provisional.final_disposition = "deep_research";
  provisional.created_at = "2026-05-06T22:03:09Z";

  assert.deepEqual(
    parseThesisVersion(provisional, {
      readinessResult: parsedReadiness,
      questionTypeVersion: "biotech_moonshot_catalyst_assessment.v1",
      workflowConfigVersion: "biotech-moonshot-catalyst-v1",
      propositionId: "biotech_moonshot_catalyst_case",
      propositionVersion: "biotech_moonshot_catalyst_case.v1",
      memoStatementIds: [
        "statement-common-ground",
        "statement-invalidation",
        "statement-gap",
        "statement-review-trigger",
      ],
      memoDisagreementIds: ["disagreement-financing-asymmetry"],
      expectedPreviousCanonicalThesisVersionId:
        "41000000-0000-4000-8000-000000000001",
      expectedBasedOnThesisVersionId:
        "41000000-0000-4000-8000-000000000001",
    }),
    provisional,
  );
});

test("records no thesis for either incomplete committee state", () => {
  for (const committeeStatus of [
    "incomplete_required_grader_failed",
    "insufficient_accepted_opinions",
  ] as const) {
    const incomplete = blockedDecisionReady();
    incomplete.committee_status = committeeStatus;
    const parsed = parseReadinessGateResult(incomplete, {
      ...upstream,
      committeeStatus,
    });
    const creation = {
      contract_version: "thesis_creation_result.v1",
      thesis_creation_result_id: committeeStatus === "incomplete_required_grader_failed"
        ? "42000000-0000-4000-8000-000000000002"
        : "42000000-0000-4000-8000-000000000003",
      operator_id: parsed.operator_id,
      security_id: parsed.security_id,
      thesis_contract_id: parsed.thesis_contract_id,
      research_run_id: parsed.research_run_id,
      committee_result_id: parsed.committee_result_id,
      readiness_gate_result_id: parsed.readiness_gate_result_id,
      committee_status: committeeStatus,
      creation_outcome: "no_thesis",
      thesis_version_id: null,
      reason_code: "incomplete_committee_no_thesis",
      created_at: "2026-05-06T22:03:10Z",
    };
    assert.deepEqual(
      parseThesisCreationResult(creation, {
        readinessResult: parsed,
        thesisVersion: null,
      }),
      creation,
    );
  }
});

test("does not allow complete or abstention committees to claim no thesis", () => {
  const parsedReadiness = parseReadinessGateResult(readiness, upstream);
  const invalidNoThesis = {
    contract_version: "thesis_creation_result.v1",
    thesis_creation_result_id: "42000000-0000-4000-8000-000000000004",
    operator_id: parsedReadiness.operator_id,
    security_id: parsedReadiness.security_id,
    thesis_contract_id: parsedReadiness.thesis_contract_id,
    research_run_id: parsedReadiness.research_run_id,
    committee_result_id: parsedReadiness.committee_result_id,
    readiness_gate_result_id: parsedReadiness.readiness_gate_result_id,
    committee_status: "complete",
    creation_outcome: "no_thesis",
    thesis_version_id: null,
    reason_code: "incorrect_no_thesis",
    created_at: "2026-05-06T22:03:10Z",
  };
  assert.throws(
    () => parseThesisCreationResult(invalidNoThesis, {
      readinessResult: parsedReadiness,
      thesisVersion: null,
    }),
    /invalid thesis creation outcome/,
  );
});

test("exposes canonical history and provisional branches without changing active canonical", () => {
  const canonical = parseCanonicalThesis();
  const provisional = structuredClone(canonical) as Record<string, any>;
  provisional.thesis_version_id = "41000000-0000-4000-8000-000000000002";
  provisional.thesis_status = "provisional";
  provisional.previous_canonical_thesis_version_id = canonical.thesis_version_id;
  provisional.based_on_thesis_version_id = canonical.thesis_version_id;
  provisional.research_run_id = "33000000-0000-4000-8000-000000000002";
  provisional.committee_result_id = "32000000-0000-4000-8000-000000000002";
  provisional.committee_memo_id = "30000000-0000-4000-8000-000000000002";
  provisional.readiness_gate_result_id = "40000000-0000-4000-8000-000000000002";
  provisional.committee_status = "complete_with_abstentions";
  provisional.final_disposition = "deep_research";
  provisional.created_at = "2026-05-06T22:03:09Z";
  const chain = {
    contract_version: "thesis_chain.v1",
    operator_id: canonical.operator_id,
    security_id: canonical.security_id,
    thesis_contract_id: canonical.thesis_contract_id,
    active_canonical_thesis_version_id: canonical.thesis_version_id,
    canonical_versions: [canonical],
    provisional_branches: [provisional],
    generated_at: "2026-05-06T22:03:11Z",
  };

  assert.deepEqual(
    parseThesisChain(chain, {
      operatorId: canonical.operator_id,
      securityId: canonical.security_id,
      thesisContractId: canonical.thesis_contract_id,
    }),
    chain,
  );
});

test("keeps a pre-canonical provisional branch when a later canonical is created", () => {
  const canonical = parseCanonicalThesis();
  const provisional = structuredClone(canonical) as Record<string, any>;
  provisional.thesis_version_id = "41000000-0000-4000-8000-000000000004";
  provisional.thesis_status = "provisional";
  provisional.previous_canonical_thesis_version_id = null;
  provisional.based_on_thesis_version_id = null;
  provisional.research_run_id = "33000000-0000-4000-8000-000000000004";
  provisional.committee_result_id = "32000000-0000-4000-8000-000000000004";
  provisional.committee_memo_id = "30000000-0000-4000-8000-000000000004";
  provisional.readiness_gate_result_id = "40000000-0000-4000-8000-000000000004";
  provisional.committee_status = "complete_with_abstentions";
  provisional.final_disposition = "deep_research";
  provisional.created_at = "2026-05-06T22:03:06Z";
  const chain = {
    contract_version: "thesis_chain.v1",
    operator_id: canonical.operator_id,
    security_id: canonical.security_id,
    thesis_contract_id: canonical.thesis_contract_id,
    active_canonical_thesis_version_id: canonical.thesis_version_id,
    canonical_versions: [canonical],
    provisional_branches: [provisional],
    generated_at: "2026-05-06T22:03:11Z",
  };

  assert.deepEqual(
    parseThesisChain(chain, {
      operatorId: canonical.operator_id,
      securityId: canonical.security_id,
      thesisContractId: canonical.thesis_contract_id,
    }),
    chain,
  );
});

test("rejects duplicate runs and provisional attempts to supersede canonical history", () => {
  const canonical = parseCanonicalThesis();
  const duplicate = structuredClone(canonical) as Record<string, any>;
  duplicate.thesis_version_id = "41000000-0000-4000-8000-000000000003";
  duplicate.created_at = "2026-05-06T22:03:09Z";
  duplicate.previous_canonical_thesis_version_id = canonical.thesis_version_id;
  duplicate.based_on_thesis_version_id = canonical.thesis_version_id;
  const duplicateRunChain = {
    contract_version: "thesis_chain.v1",
    operator_id: canonical.operator_id,
    security_id: canonical.security_id,
    thesis_contract_id: canonical.thesis_contract_id,
    active_canonical_thesis_version_id: duplicate.thesis_version_id,
    canonical_versions: [canonical, duplicate],
    provisional_branches: [],
    generated_at: "2026-05-06T22:03:11Z",
  };
  assert.throws(
    () => parseThesisChain(duplicateRunChain, {
      operatorId: canonical.operator_id,
      securityId: canonical.security_id,
      thesisContractId: canonical.thesis_contract_id,
    }),
    /duplicate thesis identity or research run/,
  );

  const failedArtifact = structuredClone(canonical) as Record<string, any>;
  failedArtifact.failure_reason = "required grader failed";
  assert.throws(
    () => parseThesisChain({
      ...duplicateRunChain,
      active_canonical_thesis_version_id: canonical.thesis_version_id,
      canonical_versions: [failedArtifact],
    }, {
      operatorId: canonical.operator_id,
      securityId: canonical.security_id,
      thesisContractId: canonical.thesis_contract_id,
    }),
    /invalid public thesis version fields/,
  );
});

test("records one deterministic canonical creation outcome for the run", () => {
  const parsedReadiness = parseReadinessGateResult(readiness, upstream);
  const parsedThesis = parseThesisVersion(canonicalThesis, {
    readinessResult: parsedReadiness,
    questionTypeVersion: "biotech_moonshot_catalyst_assessment.v1",
    workflowConfigVersion: "biotech-moonshot-catalyst-v1",
    propositionId: "biotech_moonshot_catalyst_case",
    propositionVersion: "biotech_moonshot_catalyst_case.v1",
    memoStatementIds: [
      "statement-common-ground",
      "statement-invalidation",
      "statement-gap",
      "statement-review-trigger",
    ],
    memoDisagreementIds: ["disagreement-financing-asymmetry"],
  });
  const creation = {
    contract_version: "thesis_creation_result.v1",
    thesis_creation_result_id: "42000000-0000-4000-8000-000000000001",
    operator_id: parsedReadiness.operator_id,
    security_id: parsedReadiness.security_id,
    thesis_contract_id: parsedReadiness.thesis_contract_id,
    research_run_id: parsedReadiness.research_run_id,
    committee_result_id: parsedReadiness.committee_result_id,
    readiness_gate_result_id: parsedReadiness.readiness_gate_result_id,
    committee_status: "complete",
    creation_outcome: "canonical_created",
    thesis_version_id: parsedThesis.thesis_version_id,
    reason_code: "complete_committee_canonical_created",
    created_at: "2026-05-06T22:03:08Z",
  };

  assert.deepEqual(
    parseThesisCreationResult(creation, {
      readinessResult: parsedReadiness,
      thesisVersion: parsedThesis,
    }),
    creation,
  );
});

test("publishes strict readiness and thesis schemas through the package root", () => {
  const schema = JSON.parse(
    readFileSync(new URL("./readiness-thesis.schema.json", import.meta.url), "utf8"),
  ) as Record<string, any>;
  const packageIndex = readFileSync(new URL("./index.ts", import.meta.url), "utf8");

  assert.equal(schema.$schema, "https://json-schema.org/draft/2020-12/schema");
  assert.equal(
    schema.$defs.readiness_gate_result.properties.contract_version.const,
    "readiness_gate_result.v1",
  );
  assert.equal(
    schema.$defs.thesis_version.properties.contract_version.const,
    "thesis_version.v1",
  );
  assert.equal(schema.$defs.readiness_gate_result.additionalProperties, false);
  assert.equal(schema.$defs.thesis_version.additionalProperties, false);
  assert.equal(schema.$defs.thesis_creation_result.additionalProperties, false);
  assert.equal(schema.$defs.thesis_chain.additionalProperties, false);
  assert.deepEqual(schema.$defs.check_id.enum, [
    "committee_status_complete",
    "all_eligible_graders_accepted",
    "zero_eligible_abstentions",
    "zero_required_grader_failures",
    "blocking_evidence_requirements_satisfied",
    "aligned_valuation_snapshot_required",
    "source_freshness_passed",
    "material_claims_citation_valid",
    "grader_decision_questions_answered",
    "material_disagreement_preserved",
    "thesis_required_contents_present",
  ]);
  assert.match(packageIndex, /parseReadinessGateResult/);
  assert.match(packageIndex, /parseThesisVersion/);
  assert.match(packageIndex, /parseThesisCreationResult/);
  assert.match(packageIndex, /parseThesisChain/);
  assert.doesNotMatch(
    JSON.stringify(schema),
    /target_price|trade_action|position_size|share_quantity|universal_score|vote_result/,
  );
});
