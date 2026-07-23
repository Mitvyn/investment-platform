import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseCommitteeMemo } from "./committee-memo.ts";

const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/committee_memo/v1/valid.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as unknown;

const context = {
  committeeId: "32000000-0000-4000-8000-000000000001",
  researchRunId: "33000000-0000-4000-8000-000000000001",
  evidenceBundleId: "4478d37e-95c4-545f-826c-d77257dfd4aa",
  evidenceBundleHash:
    "2d13851bd2d0b99ad5d5665506d36d181c68bd01501001f2da67fbcd6912cafe",
  workflowConfigVersion: "biotech_moonshot_catalyst_workflow.v1",
  propositionId: "biotech_moonshot_catalyst_case",
  propositionVersion: "biotech_moonshot_catalyst_case.v1",
  committeeStatus: "complete",
  evidenceIds: ["8d80b1a6-0742-5b0c-bf48-4e0d32cb8200"],
  calculationIds: ["calc-enterprise-value-v1"],
  graderResults: [
    ["moonshot", "accepted", "20000000-0000-4000-8000-000000000001", "supports"],
    ["catalyst", "accepted", "20000000-0000-4000-8000-000000000002", "mixed"],
    ["biotech", "accepted", "20000000-0000-4000-8000-000000000003", "challenges"],
    ["risk_dilution", "accepted", "20000000-0000-4000-8000-000000000004", "challenges"],
    ["valuation", "accepted", "20000000-0000-4000-8000-000000000005", "mixed"],
  ].map(([graderId, executionState, opinionId, stance]) => ({
    graderId,
    executionState,
    opinionId,
    stance,
  })),
} as const;

test("accepts one provenance-typed committee memo tied to persisted committee state", () => {
  assert.deepEqual(parseCommitteeMemo(fixture, context), fixture);
});

test("rejects memo detached from exact committee and frozen bundle identity", () => {
  const detached = structuredClone(fixture) as Record<string, unknown>;
  detached.evidence_bundle_hash = "0".repeat(64);

  assert.throws(
    () => parseCommitteeMemo(detached, context),
    /committee memo identity mismatch/,
  );
});

test("rejects statement references outside frozen evidence, opinions, or deterministic calculations", () => {
  const unknownEvidence = structuredClone(fixture) as Record<string, any>;
  unknownEvidence.statements[0].evidence_ids = [
    "00000000-0000-4000-8000-000000000000",
  ];

  const unknownOpinion = structuredClone(fixture) as Record<string, any>;
  unknownOpinion.statements[1].opinion_ids = [
    "00000000-0000-4000-8000-000000000000",
  ];

  const unknownCalculation = structuredClone(fixture) as Record<string, any>;
  unknownCalculation.statements[3].calculation_ids = ["invented-calculation"];

  for (const candidate of [unknownEvidence, unknownOpinion, unknownCalculation]) {
    assert.throws(
      () => parseCommitteeMemo(candidate, context),
      /unresolved (evidence|opinion|calculation) reference/,
    );
  }
});

test("enforces provenance-specific support for every memo statement", () => {
  const unsupportedFact = structuredClone(fixture) as Record<string, any>;
  unsupportedFact.statements[0].evidence_ids = [];

  const generalizedGraderClaim = structuredClone(fixture) as Record<string, any>;
  generalizedGraderClaim.statements[1].opinion_ids.push(
    "20000000-0000-4000-8000-000000000002",
  );

  const unsupportedSynthesis = structuredClone(fixture) as Record<string, any>;
  unsupportedSynthesis.statements[2].opinion_ids = [
    "20000000-0000-4000-8000-000000000001",
  ];

  const unsupportedGap = structuredClone(fixture) as Record<string, any>;
  unsupportedGap.statements[4].opinion_ids = [];

  for (const candidate of [
    unsupportedFact,
    generalizedGraderClaim,
    unsupportedSynthesis,
    unsupportedGap,
  ]) {
    assert.throws(
      () => parseCommitteeMemo(candidate, context),
      /invalid statement provenance support/,
    );
  }
});

test("preserves every grader execution state, opinion identity, and accepted stance exactly", () => {
  const hiddenState = structuredClone(fixture) as Record<string, any>;
  hiddenState.state_disclosure.pop();

  const relabeledState = structuredClone(fixture) as Record<string, any>;
  relabeledState.state_disclosure[0].execution_state = "abstained";

  const softenedStance = structuredClone(fixture) as Record<string, any>;
  softenedStance.state_disclosure[2].stance = "mixed";

  for (const candidate of [hiddenState, relabeledState, softenedStance]) {
    assert.throws(
      () => parseCommitteeMemo(candidate, context),
      /state disclosure mismatch/,
    );
  }
});

test("discloses accepted, abstained, failed, not-eligible, and not-executed as distinct states", () => {
  const mixed = structuredClone(fixture) as Record<string, any>;
  const opinionOne = "20000000-0000-4000-8000-000000000001";
  const opinionTwo = "20000000-0000-4000-8000-000000000002";
  mixed.committee_status = "incomplete_required_grader_failed";
  mixed.statements.forEach((statement: Record<string, any>) => {
    if (statement.provenance_type === "fact") return;
    statement.opinion_ids = statement.provenance_type === "synthesis_interpretation"
      ? [opinionOne, opinionTwo]
      : [statement.provenance_type === "grader_interpretation" ? opinionOne : opinionTwo];
  });
  mixed.disagreement_records[0].contributing_opinion_ids = [opinionOne, opinionTwo];
  mixed.state_disclosure = [
    {grader_id: "moonshot", execution_state: "accepted", opinion_id: opinionOne, stance: "supports"},
    {grader_id: "catalyst", execution_state: "abstained", opinion_id: opinionTwo, stance: null},
    {grader_id: "biotech", execution_state: "failed", opinion_id: null, stance: null},
    {grader_id: "risk_dilution", execution_state: "not_eligible", opinion_id: null, stance: null},
    {grader_id: "valuation", execution_state: "not_executed", opinion_id: null, stance: null},
  ];
  const mixedContext = {
    ...context,
    committeeStatus: "incomplete_required_grader_failed",
    graderResults: mixed.state_disclosure.map((result: Record<string, any>) => ({
      graderId: result.grader_id,
      executionState: result.execution_state,
      opinionId: result.opinion_id,
      stance: result.stance,
    })),
  } as any;

  assert.deepEqual(parseCommitteeMemo(mixed, mixedContext), mixed);
});

test("requires memo sections and disagreement records to resolve to typed contributing statements", () => {
  const inventedGap = structuredClone(fixture) as Record<string, any>;
  inventedGap.evidence_gap_statement_ids = ["statement-not-present"];

  const hiddenContributor = structuredClone(fixture) as Record<string, any>;
  hiddenContributor.disagreement_records[0].contributing_opinion_ids = [
    "20000000-0000-4000-8000-000000000001",
  ];

  for (const candidate of [inventedGap, hiddenContributor]) {
    assert.throws(
      () => parseCommitteeMemo(candidate, context),
      /invalid memo section provenance/,
    );
  }
});

test("rejects target price, trade action, position sizing, calculation, score, and vote authority", () => {
  const targetPrice = structuredClone(fixture) as Record<string, any>;
  targetPrice.target_price = "12.00";

  const tradeAction = structuredClone(fixture) as Record<string, any>;
  tradeAction.statements[2].text = "Recommend buy action after committee review.";

  const hiddenCalculation = structuredClone(fixture) as Record<string, any>;
  hiddenCalculation.statements[3].calculated_value = "42";

  const universalScore = structuredClone(fixture) as Record<string, any>;
  universalScore.statements[2].text = "Weighted score is 84 after majority vote.";

  for (const candidate of [targetPrice, tradeAction, hiddenCalculation, universalScore]) {
    assert.throws(
      () => parseCommitteeMemo(candidate, context),
      /prohibited synthesizer output|invalid committee memo fields|invalid statement fields/,
    );
  }
});

test("permits only research disposition requests and never records readiness grant", () => {
  const requestedReady = structuredClone(fixture) as Record<string, any>;
  requestedReady.requested_disposition = "decision_ready";
  assert.deepEqual(parseCommitteeMemo(requestedReady, context), requestedReady);

  const tradeDisposition = structuredClone(fixture) as Record<string, any>;
  tradeDisposition.requested_disposition = "buy";
  assert.throws(
    () => parseCommitteeMemo(tradeDisposition, context),
    /invalid requested disposition/,
  );
});

test("validates bounded synthesis attempt and token-cost execution metadata", () => {
  const badAttempts = structuredClone(fixture) as Record<string, any>;
  badAttempts.execution_metadata.attempt_count = 3;

  const badUsage = structuredClone(fixture) as Record<string, any>;
  badUsage.execution_metadata.total_tokens += 1;

  const hiddenRawOutput = structuredClone(fixture) as Record<string, any>;
  hiddenRawOutput.execution_metadata.raw_response = {text: "private"};

  for (const candidate of [badAttempts, badUsage, hiddenRawOutput]) {
    assert.throws(
      () => parseCommitteeMemo(candidate, context),
      /invalid synthesis execution metadata/,
    );
  }
});

test("preserves bounded synthesis attempt chronology, validation, usage, and cost without raw bodies", () => {
  const parsed = parseCommitteeMemo(fixture, context);

  assert.equal(parsed.execution_metadata.reasoning_tokens, 300);
  assert.equal(parsed.execution_metadata.usage_complete, true);
  assert.deepEqual(parsed.execution_metadata.attempts[0], {
    attempt_id: "34000000-0000-4000-8000-000000000001",
    attempt_number: 1,
    provider_request_id: "offline-request-001",
    result: "accepted",
    validation_status: "passed",
    validation_errors: [],
    retry_reason: null,
    started_at: "2026-05-06T22:03:00Z",
    completed_at: "2026-05-06T22:03:04Z",
    duration_ms: 4000,
    input_tokens: 3200,
    cached_input_tokens: 500,
    cache_write_tokens: 700,
    uncached_input_tokens: 2000,
    output_tokens: 900,
    reasoning_tokens: 300,
    total_tokens: 4100,
    usage_complete: true,
    estimated_cost_usd: "0.000000",
  });
  assert.doesNotMatch(
    JSON.stringify(parsed.execution_metadata),
    /raw_request|raw_response|reasoning_content/,
  );
});

test("validates mutually exclusive synthesis input-token categories", () => {
  const categorized = structuredClone(fixture) as Record<string, any>;
  categorized.execution_metadata.cached_input_tokens = 500;
  categorized.execution_metadata.cache_write_tokens = 700;
  categorized.execution_metadata.uncached_input_tokens = 2000;

  assert.deepEqual(parseCommitteeMemo(categorized, context), categorized);

  categorized.execution_metadata.uncached_input_tokens = 2001;
  assert.throws(
    () => parseCommitteeMemo(categorized, context),
    /invalid synthesis execution metadata/,
  );
});

test("rejects untyped nested memo content and duplicate provenance identities", () => {
  const disagreementCommentary = structuredClone(fixture) as Record<string, any>;
  disagreementCommentary.disagreement_records[0].resolution = "Synthesizer decides.";

  const triggerAction = structuredClone(fixture) as Record<string, any>;
  triggerAction.review_trigger.trade_action = "buy";

  const duplicateStatement = structuredClone(fixture) as Record<string, any>;
  duplicateStatement.statements[1].statement_id = duplicateStatement.statements[0].statement_id;

  const duplicateCitation = structuredClone(fixture) as Record<string, any>;
  duplicateCitation.statements[0].evidence_ids.push(
    duplicateCitation.statements[0].evidence_ids[0],
  );

  for (const candidate of [
    disagreementCommentary,
    triggerAction,
    duplicateStatement,
    duplicateCitation,
  ]) {
    assert.throws(() => parseCommitteeMemo(candidate, context), TypeError);
  }
});

test("publishes strict Committee Memo v1 schema and package-root parser", () => {
  const schema = JSON.parse(
    readFileSync(new URL("./committee-memo.schema.json", import.meta.url), "utf8"),
  ) as Record<string, any>;
  const packageIndex = readFileSync(new URL("./index.ts", import.meta.url), "utf8");

  assert.match(packageIndex, /parseCommitteeMemo/);
  assert.match(packageIndex, /type CommitteeMemo/);
  assert.equal(schema.$schema, "https://json-schema.org/draft/2020-12/schema");
  assert.equal(schema.properties.contract_version.const, "committee_memo.v1");
  assert.equal(schema.additionalProperties, false);
  assert.deepEqual(schema.$defs.statement.properties.provenance_type.enum, [
    "fact",
    "grader_interpretation",
    "synthesis_interpretation",
    "assumption",
    "gap",
  ]);
  assert.deepEqual(schema.properties.requested_disposition.enum, [
    "reject",
    "monitor",
    "deep_research",
    "decision_ready",
  ]);
  assert.equal(schema.$defs.statement.additionalProperties, false);
  assert.equal(schema.$defs.disagreement.additionalProperties, false);
  assert.equal(schema.$defs.state_disclosure.additionalProperties, false);
  assert.equal(schema.$defs.execution_metadata.additionalProperties, false);
  assert.equal(schema.$defs.synthesis_attempt.additionalProperties, false);
  for (const field of [
    "cached_input_tokens",
    "cache_write_tokens",
    "uncached_input_tokens",
    "reasoning_tokens",
  ]) {
    assert.ok(schema.$defs.execution_metadata.required.includes(field));
    assert.equal(
      schema.$defs.execution_metadata.properties[field].minimum,
      0,
    );
  }
  assert.ok(schema.$defs.execution_metadata.required.includes("attempts"));
  assert.ok(schema.$defs.execution_metadata.required.includes("usage_complete"));
  assert.doesNotMatch(
    JSON.stringify(schema),
    /target_price|trade_action|position_size|universal_score|vote_result|calculated_value/,
  );
});

test("requires stable memo identities and synthesis-before-persistence timestamps", () => {
  const malformedId = structuredClone(fixture) as Record<string, any>;
  malformedId.memo_id = "memo-1";

  const earlyPersistence = structuredClone(fixture) as Record<string, any>;
  earlyPersistence.created_at = "2026-05-06T22:02:59Z";

  for (const candidate of [malformedId, earlyPersistence]) {
    assert.throws(
      () => parseCommitteeMemo(candidate, context),
      /invalid committee memo identity or timestamp/,
    );
  }
});
