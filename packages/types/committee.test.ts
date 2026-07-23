import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  deriveCommitteeState,
  MVP_COMMITTEE_ROSTER,
  parseCommitteeGraderResult,
  parseCommitteeState,
} from "./committee.ts";

const bundleContext = {
  evidenceBundleId: "4478d37e-95c4-545f-826c-d77257dfd4aa",
  evidenceBundleHash:
    "2d13851bd2d0b99ad5d5665506d36d181c68bd01501001f2da67fbcd6912cafe",
  evidenceIds: ["8d80b1a6-0742-5b0c-bf48-4e0d32cb8200"],
  calculationIds: ["calc-enterprise-value-v1"],
} as const;

const domainPayloads = {
  moonshot: {
    contract_version: "moonshot_grader_payload.v1",
    mission_relevance: "material",
    asymmetry_assessment: "credible",
    evidence_maturity: "clinical",
    strategic_or_societal_value: "material",
    asymmetry_drivers: ["Platform could address several diseases."],
    limiting_factors: ["Clinical translation remains uncertain."],
  },
  catalyst: {
    contract_version: "catalyst_grader_payload.v1",
    catalyst_definition: "Phase 2 efficacy readout",
    programme: "Lead programme",
    probability: {
      value: "0.45",
      unit: "probability",
      calculation_method: "Evidence-weighted scenario estimate",
      assumptions: ["Trial completes as guided."],
      evidence_ids: [...bundleContext.evidenceIds],
      calculation_ids: [],
    },
    timing_window: "2027-H1",
    date_confidence: "medium",
    success_outcome: "Endpoint met.",
    delay_outcome: "Readout moves beyond 2027-H1.",
    partial_success_outcome: "Signal supports another study.",
    failure_outcome: "Endpoint missed.",
  },
  biotech: {
    contract_version: "biotech_grader_payload.v1",
    mechanism_plausibility: "credible",
    preclinical_evidence_quality: "moderate",
    clinical_evidence_quality: "moderate",
    trial_design_assessment: "Appropriate controlled design.",
    endpoint_relevance: "clinically_meaningful",
    regulatory_credibility: "credible",
    claims_exceed_evidence: false,
    limitations: ["Small early cohort."],
  },
  risk_dilution: {
    contract_version: "risk_dilution_grader_payload.v1",
    cash_runway: {
      value: "18",
      unit: "months",
      calculation_method: "Cash divided by quarterly operating burn",
      assumptions: ["Burn remains constant."],
      evidence_ids: [...bundleContext.evidenceIds],
      calculation_ids: ["calc-enterprise-value-v1"],
    },
    burn_rate: {
      value: "25",
      unit: "USD_millions_per_quarter",
      calculation_method: "Trailing two-quarter mean",
      assumptions: ["No material programme expansion."],
      evidence_ids: [...bundleContext.evidenceIds],
      calculation_ids: [],
    },
    going_concern_risk: "moderate",
    dilution_mechanisms: ["ATM"],
    financing_required_before_catalyst: "possible",
    downside_mechanisms: ["Trial failure"],
    permanent_capital_loss_mechanisms: ["Dilutive financing before data"],
  },
  valuation: {
    contract_version: "valuation_grader_payload.v1",
    valuation_method: "Probability-weighted scenario analysis",
    current_market_value: {
      value: "800",
      unit: "USD_millions",
      calculation_method: "Official close times fully diluted shares",
      assumptions: ["Share basis reconciled."],
      evidence_ids: [...bundleContext.evidenceIds],
      calculation_ids: ["calc-enterprise-value-v1"],
    },
    fully_diluted_shares: {
      value: "250",
      unit: "millions_of_shares",
      calculation_method: "Basic shares plus dilutive instruments",
      assumptions: ["All in-the-money instruments included."],
      evidence_ids: [...bundleContext.evidenceIds],
      calculation_ids: ["calc-enterprise-value-v1"],
    },
    scenarios: (["conservative", "base", "bull", "failure"] as const).map(
      (scenarioCase, index) => ({
        scenario_id: `valuation-${scenarioCase}`,
        case: scenarioCase,
        probability: {
          value: ["0.25", "0.35", "0.15", "0.25"][index],
          unit: "probability",
          calculation_method: "Scenario assumption",
          assumptions: [`${scenarioCase} case occurs.`],
          evidence_ids: [...bundleContext.evidenceIds],
          calculation_ids: [],
        },
        equity_value: {
          value: ["600", "1200", "2400", "300"][index],
          unit: "USD_millions",
          calculation_method: "Cash-adjusted scenario value",
          assumptions: ["Scenario assumptions hold."],
          evidence_ids: [...bundleContext.evidenceIds],
          calculation_ids: ["calc-enterprise-value-v1"],
        },
        implied_value_per_diluted_share: {
          value: ["2.4", "4.8", "9.6", "1.2"][index],
          unit: "USD_per_share",
          calculation_method: "Equity value divided by fully diluted shares",
          assumptions: ["Fully diluted share count remains 250 million."],
          evidence_ids: [...bundleContext.evidenceIds],
          calculation_ids: ["calc-enterprise-value-v1"],
        },
        assumptions: ["No unmodelled financing."],
      }),
    ),
    sensitivities: ["Clinical probability", "Fully diluted shares"],
  },
} as const;

function acceptedResult(graderId: keyof typeof domainPayloads, index = 0) {
  const definition = MVP_COMMITTEE_ROSTER.find(
    (candidate) => candidate.grader_id === graderId,
  )!;
  const suffix = String(index + 1).padStart(12, "0");
  return {
    contract_version: "committee_grader_result.v1",
    grader_id: graderId,
    grader_version: definition.grader_version,
    grader_contract_version: definition.grader_contract_version,
    output_schema_version: definition.output_schema_version,
    required: true,
    evidence_bundle_id: bundleContext.evidenceBundleId,
    evidence_bundle_hash: bundleContext.evidenceBundleHash,
    execution_id: `10000000-0000-4000-8000-${suffix}`,
    execution_state: "accepted",
    opinion: {
      opinion_id: `20000000-0000-4000-8000-${suffix}`,
      owned_decision_question: definition.owned_decision_question,
      stance: index % 3 === 0 ? "supports" : index % 3 === 1 ? "mixed" : "challenges",
      confidence: "medium",
      summary: `${graderId} conclusion`,
      material_claims: [
        {
          claim_id: `${graderId}-claim-1`,
          claim: `${graderId} material claim`,
          materiality: "high",
          evidence_ids: [...bundleContext.evidenceIds],
        },
      ],
      assumptions: ["Evidence remains current at cutoff."],
      contradicting_evidence: [],
      evidence_gaps: [],
      invalidation_signals: ["New primary evidence contradicts conclusion."],
      proposition: {
        proposition_id: "biotech_moonshot_catalyst_case",
        proposition_version: "biotech_moonshot_catalyst_case.v1",
        rendered_proposition_text:
          "As of the cutoff, the available evidence supports a credible Moonshot research case with an identifiable catalyst capable of materially resolving uncertainty.",
        grader_stance:
          index % 3 === 0 ? "supports" : index % 3 === 1 ? "mixed" : "challenges",
        stance_rationale: `${graderId} mapping to shared proposition`,
      },
      execution_metadata: {
        execution_id: `10000000-0000-4000-8000-${suffix}`,
        grader_execution_contract_version: "grader_execution.v1",
        prompt_version: `${graderId}_grader_v1`,
        model_config_id:
          "biotech_committee_graders_openai_sol_medium_v1",
        provider: "openai",
        model: "gpt-5.6-sol",
        attempt_count: 1,
      },
      domain_payload: structuredClone(domainPayloads[graderId]),
      abstention: null,
      created_at: "2026-05-06T22:01:04Z",
    },
    not_eligible: null,
    not_executed: null,
    failure: null,
    persisted_at: "2026-05-06T22:01:05Z",
  };
}

function abstainedResult(graderId: keyof typeof domainPayloads, index = 0) {
  const result = acceptedResult(graderId, index) as Record<string, any>;
  result.execution_state = "abstained";
  result.opinion.stance = null;
  result.opinion.proposition.grader_stance = null;
  result.opinion.proposition.stance_rationale = null;
  result.opinion.abstention = {
    reason_code: "evidence_insufficient",
    reason: "Frozen bundle cannot support defensible verdict.",
    missing_or_inadequate_evidence: ["Mature efficacy evidence"],
    evidence_required: ["Controlled clinical readout"],
    confidence: "high",
  };
  return result;
}

function failedResult(graderId: keyof typeof domainPayloads, index = 0) {
  const result = acceptedResult(graderId, index) as Record<string, any>;
  result.execution_state = "failed";
  result.opinion = null;
  result.failure = {
    category: "schema_validation",
    attempt_count: 2,
    validation_errors: ["schema.required:summary"],
    final_reason: "Bounded retries exhausted.",
    retry_policy_version: "grader_retry.v1",
  };
  return result;
}

function notEligibleResult(graderId: keyof typeof domainPayloads, index = 0) {
  const result = acceptedResult(graderId, index) as Record<string, any>;
  result.execution_state = "not_eligible";
  result.execution_id = null;
  result.opinion = null;
  result.not_eligible = {
    eligibility_rule_version: `${graderId}_eligibility.v1`,
    eligibility_inputs: { workflow_eligible: false },
    reason_code: "grader_not_applicable",
    reason: "Versioned grader eligibility rule does not apply.",
    evaluated_at: "2026-05-06T22:01:00Z",
  };
  return result;
}

function notExecutedResult(graderId: keyof typeof domainPayloads, index = 0) {
  const result = acceptedResult(graderId, index) as Record<string, any>;
  result.execution_state = "not_executed";
  result.execution_id = null;
  result.opinion = null;
  result.not_executed = {
    reason_code: "budget_unavailable",
    reason: "Pre-call budget gate blocked execution.",
    gate_policy_version: "model_execution_gate.v1",
    failed_gate_checks: ["budget_available"],
  };
  return result;
}

test("locks exactly five versioned specialist graders without ticker routing", () => {
  assert.deepEqual(
    MVP_COMMITTEE_ROSTER.map((grader) => grader.grader_id),
    ["moonshot", "catalyst", "biotech", "risk_dilution", "valuation"],
  );
  assert.equal(MVP_COMMITTEE_ROSTER.length, 5);
  for (const grader of MVP_COMMITTEE_ROSTER) {
    assert.equal(grader.required_when_eligible, true);
    assert.equal(grader.grader_version, `${grader.grader_id}-grader-v1`);
    assert.equal(
      grader.grader_contract_version,
      `${grader.grader_id}-grader-contract-v1`,
    );
    assert.match(grader.output_schema_version, /^[a-z_]+_grader_payload\.v1$/);
    assert.doesNotMatch(JSON.stringify(grader), /RXRX|ticker|symbol/i);
  }
});

test("validates common opinion envelope plus each grader-owned domain payload", () => {
  const results = MVP_COMMITTEE_ROSTER.map((definition, index) =>
    acceptedResult(definition.grader_id, index),
  );

  assert.deepEqual(
    results.map((result) => parseCommitteeGraderResult(result, bundleContext)),
    results,
  );
});

test("rejects peer state, universal grades, investment actions, and unsupported numeric references", () => {
  const candidates = [
    (() => {
      const value = acceptedResult("catalyst") as Record<string, any>;
      value.peer_opinions = [];
      return value;
    })(),
    (() => {
      const value = acceptedResult("moonshot") as Record<string, any>;
      value.opinion.universal_score = 91;
      return value;
    })(),
    (() => {
      const value = acceptedResult("valuation") as Record<string, any>;
      value.opinion.domain_payload.target_price = "12.00";
      return value;
    })(),
    (() => {
      const value = acceptedResult("risk_dilution") as Record<string, any>;
      value.opinion.domain_payload.cash_runway.evidence_ids = [
        "00000000-0000-4000-8000-000000000000",
      ];
      return value;
    })(),
  ];

  for (const candidate of candidates) {
    assert.throws(
      () => parseCommitteeGraderResult(candidate, bundleContext),
      TypeError,
    );
  }
});

test("derives complete committee accounting and directional matrix from five persisted accepted opinions", () => {
  const results = MVP_COMMITTEE_ROSTER.map((definition, index) =>
    acceptedResult(definition.grader_id, index),
  );

  const committee = deriveCommitteeState(results, {
    ...bundleContext,
    researchRunId: "984cce87-acde-4c65-8566-86fe27d21df3",
    workflowConfigVersion: "biotech_committee.v1",
    derivedAt: "2026-05-06T22:02:00Z",
  });

  assert.equal(committee.committee_status, "complete");
  assert.deepEqual(committee.accounting, {
    eligible_count: 5,
    accepted_count: 5,
    abstained_count: 0,
    not_eligible_count: 0,
    failed_count: 0,
    not_executed_count: 0,
  });
  assert.deepEqual(committee.stance_counts, {
    supports: 2,
    mixed: 2,
    challenges: 1,
  });
  assert.equal(committee.stance_matrix.length, 5);
  assert.deepEqual(
    committee.stance_matrix.map((entry) => entry.grader_id),
    MVP_COMMITTEE_ROSTER.map((grader) => grader.grader_id),
  );
});

test("keeps abstained, failed, not eligible, and not executed states distinct in deterministic status precedence", () => {
  const derive = (results: unknown[]) => deriveCommitteeState(results, {
    ...bundleContext,
    researchRunId: "984cce87-acde-4c65-8566-86fe27d21df3",
    workflowConfigVersion: "biotech_committee.v1",
    derivedAt: "2026-05-06T22:02:00Z",
  });
  const accepted = MVP_COMMITTEE_ROSTER.map((definition, index) =>
    acceptedResult(definition.grader_id, index),
  );

  const abstained = structuredClone(accepted);
  abstained[4] = abstainedResult("valuation", 4);
  const abstainedCommittee = derive(abstained);
  assert.equal(abstainedCommittee.committee_status, "complete_with_abstentions");
  assert.equal(abstainedCommittee.accounting.abstained_count, 1);
  assert.equal(abstainedCommittee.stance_matrix.length, 4);

  const failed = structuredClone(abstained);
  failed[2] = failedResult("biotech", 2);
  assert.equal(
    derive(failed).committee_status,
    "incomplete_required_grader_failed",
  );

  const notExecuted = structuredClone(accepted);
  notExecuted[1] = notExecutedResult("catalyst", 1);
  assert.equal(
    derive(notExecuted).committee_status,
    "insufficient_accepted_opinions",
  );

  const notEligible = structuredClone(accepted);
  notEligible[0] = notEligibleResult("moonshot", 0);
  const eligibleCommittee = derive(notEligible);
  assert.equal(eligibleCommittee.committee_status, "complete");
  assert.equal(eligibleCommittee.accounting.eligible_count, 4);
  assert.equal(eligibleCommittee.accounting.not_eligible_count, 1);
});

test("parses persisted committee state only when accounting and stance matrix match deterministic derivation", () => {
  const state = deriveCommitteeState(
    MVP_COMMITTEE_ROSTER.map((definition, index) =>
      acceptedResult(definition.grader_id, index),
    ),
    {
      ...bundleContext,
      researchRunId: "984cce87-acde-4c65-8566-86fe27d21df3",
      workflowConfigVersion: "biotech_committee.v1",
      derivedAt: "2026-05-06T22:02:00Z",
    },
  );

  assert.deepEqual(parseCommitteeState(state, bundleContext), state);

  const altered = structuredClone(state);
  altered.accounting.accepted_count = 4;
  assert.throws(
    () => parseCommitteeState(altered, bundleContext),
    /deterministic derivation/,
  );
});

test("publishes strict Committee State v1 schema and package-root exports", () => {
  const publicTypes = readFileSync(new URL("./index.ts", import.meta.url), "utf8");
  const schema = JSON.parse(
    readFileSync(new URL("./committee.schema.json", import.meta.url), "utf8"),
  ) as Record<string, any>;

  assert.match(publicTypes, /parseCommitteeState/);
  assert.match(publicTypes, /deriveCommitteeState/);
  assert.equal(schema.$schema, "https://json-schema.org/draft/2020-12/schema");
  assert.equal(schema.properties.contract_version.const, "committee_state.v1");
  assert.equal(schema.additionalProperties, false);
  assert.equal(schema.$defs.grader_result.additionalProperties, false);
  assert.equal(schema.$defs.opinion.additionalProperties, false);
  assert.equal(schema.$defs.numeric_value.additionalProperties, false);
  assert.deepEqual(schema.$defs.grader_id.enum, [
    "moonshot",
    "catalyst",
    "biotech",
    "risk_dilution",
    "valuation",
  ]);
  assert.doesNotMatch(
    JSON.stringify(schema),
    /universal_score|target_price|trade_action|position_size|peer_opinions/,
  );
});

test("round trips cross-language all-not-eligible committee fixture", () => {
  const fixture = JSON.parse(
    readFileSync(
      new URL(
        "../../tests/fixtures/contracts/committee/v1/all-not-eligible.json",
        import.meta.url,
      ),
      "utf8",
    ),
  ) as unknown;

  assert.deepEqual(parseCommitteeState(fixture, bundleContext), fixture);
});

test("derives only after five uniquely persisted terminal results", () => {
  const context = {
    ...bundleContext,
    researchRunId: "984cce87-acde-4c65-8566-86fe27d21df3",
    workflowConfigVersion: "biotech_committee.v1",
    derivedAt: "2026-05-06T22:02:00Z",
  };
  const duplicateExecution = MVP_COMMITTEE_ROSTER.map((definition, index) =>
    acceptedResult(definition.grader_id, index),
  ) as Record<string, any>[];
  duplicateExecution[1].execution_id = duplicateExecution[0].execution_id;
  duplicateExecution[1].opinion.execution_metadata.execution_id =
    duplicateExecution[0].execution_id;
  assert.throws(
    () => deriveCommitteeState(duplicateExecution, context),
    /duplicate execution identity/,
  );

  const notYetPersisted = MVP_COMMITTEE_ROSTER.map((definition, index) =>
    acceptedResult(definition.grader_id, index),
  ) as Record<string, any>[];
  notYetPersisted[0].persisted_at = context.derivedAt;
  assert.throws(
    () => deriveCommitteeState(notYetPersisted, context),
    /persist before committee derivation/,
  );
});
