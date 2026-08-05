import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  deriveOperatorDecisionCurrentState,
  deriveOperatorDecisionRelationship,
  parseOperatorDecisionEvent,
  parseOperatorDecisionHistory,
  parseOperatorWorkflowCommand,
  parsePortfolioReviewHandoffMarker,
  resolveOperatorDecisionReplay,
  resolveOperatorWorkflowCommandReplay,
  resolvePortfolioReviewHandoffReplay,
} from "./operator-decision.ts";
import { parseReadinessGateResult, parseThesisVersion } from "./readiness-thesis.ts";

const readinessRaw = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/readiness_thesis/v1/decision-ready.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, unknown>;

const thesisRaw = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/readiness_thesis/v1/canonical-thesis.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, unknown>;

const decisionReadyHandoff = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/operator_decision/v1/decision-ready-handoff.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, unknown>;

const deepResearchCommand = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/operator_decision/v1/deep-research-command.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, unknown>;

const portfolioReviewHandoff = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/operator_decision/v1/portfolio-review-handoff.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, unknown>;

const readiness = parseReadinessGateResult(readinessRaw, {
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
});

const thesis = parseThesisVersion(thesisRaw, {
  readinessResult: readiness,
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

const upstream = { thesisVersion: thesis, readinessResult: readiness };

const personalReadiness = parseReadinessGateResult(
  {
    ...readinessRaw,
    thesis_contract_id: "biotech_moonshot_catalyst_personal_research_v1",
    gate_policy_version: "biotech-personal-readiness.v1",
  },
  {
    operatorId: readiness.operator_id,
    securityId: readiness.security_id,
    thesisContractId: "biotech_moonshot_catalyst_personal_research_v1",
    researchRunId: readiness.research_run_id,
    evidenceBundleId: readiness.evidence_bundle_id,
    evidenceBundleHash: readiness.evidence_bundle_hash,
    validatedGraderOpinionIds: readiness.validated_grader_opinion_ids,
    committeeResultId: readiness.committee_result_id,
    committeeMemoId: readiness.committee_memo_id,
    committeeStatus: readiness.committee_status,
    requestedDisposition: readiness.requested_disposition,
  },
);

const personalThesis = parseThesisVersion(
  {
    ...thesisRaw,
    thesis_contract_id: "biotech_moonshot_catalyst_personal_research_v1",
    question_type_version:
      "biotech_moonshot_catalyst_personal_research_assessment.v1",
    workflow_config_version:
      "biotech-moonshot-catalyst-personal-research-v1",
    readiness_gate_policy_version: "biotech-personal-readiness.v1",
  },
  {
    readinessResult: personalReadiness,
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
  },
);

const personalUpstream = {
  thesisVersion: personalThesis,
  readinessResult: personalReadiness,
};

test("accepts an immutable operator decision tied to exact thesis and readiness output", () => {
  assert.deepEqual(
    parseOperatorDecisionEvent(decisionReadyHandoff, upstream),
    decisionReadyHandoff,
  );
});

test("accepts non-handoff actions for personal-research thesis history", () => {
  const personalDecision = {
    ...decisionReadyHandoff,
    thesis_contract_id: "biotech_moonshot_catalyst_personal_research_v1",
    operator_action: "no_action",
    relationship: "defer",
    rationale: "Reviewed within lower-assurance personal research boundary.",
    idempotency_key: "personal-research:no-action",
  };

  assert.deepEqual(
    parseOperatorDecisionEvent(personalDecision, personalUpstream),
    personalDecision,
  );
});

test("rejects portfolio-handoff action for personal-research thesis", () => {
  assert.throws(
    () =>
      parseOperatorDecisionEvent(
        {
          ...decisionReadyHandoff,
          thesis_contract_id:
            "biotech_moonshot_catalyst_personal_research_v1",
        },
        personalUpstream,
      ),
    /personal research thesis cannot create portfolio handoff/,
  );
});

test("accepts separate deep-research command for personal-research thesis", () => {
  const decision = parseOperatorDecisionEvent(
    {
      ...decisionReadyHandoff,
      operator_decision_id: "50000000-0000-4000-8000-000000000003",
      thesis_contract_id:
        "biotech_moonshot_catalyst_personal_research_v1",
      operator_action: "request_deep_research",
      relationship: "override",
      rationale: "Collect stronger evidence before another personal run.",
      idempotency_key: "personal-research:deep-research",
      created_at: "2026-05-06T22:07:30Z",
    },
    personalUpstream,
  );
  const command = {
    ...deepResearchCommand,
    thesis_contract_id:
      "biotech_moonshot_catalyst_personal_research_v1",
  };

  assert.deepEqual(
    parseOperatorWorkflowCommand(command, { decision }),
    command,
  );
});

test("derives accept, defer, or override from disposition and action policy", () => {
  assert.equal(deriveOperatorDecisionRelationship("reject", "dismiss"), "accept");
  assert.equal(deriveOperatorDecisionRelationship("monitor", "monitor"), "accept");
  assert.equal(
    deriveOperatorDecisionRelationship("deep_research", "request_deep_research"),
    "accept",
  );
  assert.equal(
    deriveOperatorDecisionRelationship(
      "decision_ready",
      "mark_for_future_portfolio_review",
    ),
    "accept",
  );
  assert.equal(
    deriveOperatorDecisionRelationship("decision_ready", "no_action"),
    "defer",
  );
  assert.equal(
    deriveOperatorDecisionRelationship("monitor", "request_deep_research"),
    "override",
  );
});

test("requires rationale for an override and rejects research mutation fields", () => {
  const override = structuredClone(decisionReadyHandoff) as Record<string, unknown>;
  override.operator_action = "monitor";
  override.relationship = "override";
  override.rationale = "";
  assert.throws(
    () => parseOperatorDecisionEvent(override, upstream),
    /override requires rationale/,
  );

  override.rationale = "Prefer monitoring before portfolio-fit review.";
  for (const prohibitedField of [
    "changed_system_disposition",
    "thesis_patch",
    "committee_patch",
    "readiness_override",
    "opinion_patch",
    "failed_grader_patch",
    "abstention_patch",
    "blocking_reason_patch",
    "position_size",
    "allocation",
    "trade_action",
    "order",
    "portfolio_suitability",
  ]) {
    const mutated = { ...override, [prohibitedField]: "prohibited" };
    assert.throws(
      () => parseOperatorDecisionEvent(mutated, upstream),
      /invalid operator decision event fields/,
    );
  }
});

test("preserves supersession history and derives current operator state separately", () => {
  const first = parseOperatorDecisionEvent(decisionReadyHandoff, upstream);
  const deferred = {
    ...first,
    operator_decision_id: "50000000-0000-4000-8000-000000000002",
    operator_action: "no_action",
    relationship: "defer",
    rationale: "Pause before handing off to portfolio fit.",
    supersedes_operator_decision_id: first.operator_decision_id,
    idempotency_key: "decision:operator-a:rxrx:thesis-v1:defer",
    created_at: "2026-05-06T22:06:00Z",
  } as const;
  const history = {
    contract_version: "operator_decision_history.v1",
    operator_id: first.operator_id,
    security_id: first.security_id,
    thesis_contract_id: first.thesis_contract_id,
    events: [first, deferred],
    generated_at: "2026-05-06T22:07:00Z",
  };

  const parsed = parseOperatorDecisionHistory(history, upstream);
  assert.equal(parsed.events.length, 2);
  assert.deepEqual(
    deriveOperatorDecisionCurrentState(parsed, "2026-05-06T22:07:01Z"),
    {
      contract_version: "operator_decision_current_state.v1",
      operator_id: first.operator_id,
      security_id: first.security_id,
      thesis_contract_id: first.thesis_contract_id,
      current_operator_decision_id: deferred.operator_decision_id,
      current_operator_action: "no_action",
      current_relationship: "defer",
      supersession_depth: 1,
      derived_at: "2026-05-06T22:07:01Z",
    },
  );
});

test("validates a separate idempotent research-request command for deep research", () => {
  const decision = parseOperatorDecisionEvent(
    {
      ...decisionReadyHandoff,
      operator_decision_id: "50000000-0000-4000-8000-000000000003",
      operator_action: "request_deep_research",
      relationship: "override",
      rationale: "Collect another financing filing before portfolio fit.",
      idempotency_key: "decision:operator-a:rxrx:thesis-v1:deep-research",
      created_at: "2026-05-06T22:07:30Z",
    },
    upstream,
  );

  assert.deepEqual(
    parseOperatorWorkflowCommand(deepResearchCommand, { decision }),
    deepResearchCommand,
  );
});

test("accepts a marker only for a canonical decision-ready thesis with passed readiness", () => {
  const decision = parseOperatorDecisionEvent(decisionReadyHandoff, upstream);
  assert.deepEqual(
    parsePortfolioReviewHandoffMarker(portfolioReviewHandoff, {
      decision,
      thesisVersion: thesis,
      readinessResult: readiness,
    }),
    portfolioReviewHandoff,
  );
});

test("rejects portfolio handoff for provisional thesis, failed gate, other disposition, or override", () => {
  const acceptedDecision = parseOperatorDecisionEvent(decisionReadyHandoff, upstream);
  const provisionalThesis = { ...thesis, thesis_status: "provisional" } as typeof thesis;
  assert.throws(
    () =>
      parsePortfolioReviewHandoffMarker(portfolioReviewHandoff, {
        decision: acceptedDecision,
        thesisVersion: provisionalThesis,
        readinessResult: readiness,
      }),
    /requires canonical thesis/,
  );

  const blockedReadiness = { ...readiness, readiness_status: "blocked" } as typeof readiness;
  assert.throws(
    () =>
      parsePortfolioReviewHandoffMarker(
        { ...portfolioReviewHandoff, readiness_status: "blocked" },
        {
          decision: acceptedDecision,
          thesisVersion: thesis,
          readinessResult: blockedReadiness,
        },
      ),
    /requires passed readiness gate/,
  );

  const overrideDecision = parseOperatorDecisionEvent(
    {
      ...decisionReadyHandoff,
      operator_action: "monitor",
      relationship: "override",
      rationale: "Continue monitoring instead.",
    },
    upstream,
  );
  assert.throws(
    () =>
      parsePortfolioReviewHandoffMarker(portfolioReviewHandoff, {
        decision: overrideDecision,
        thesisVersion: thesis,
        readinessResult: readiness,
      }),
    /requires accepted handoff decision/,
  );

  const deepResearchDecision = {
    ...acceptedDecision,
    system_disposition: "deep_research",
    operator_action: "mark_for_future_portfolio_review",
    relationship: "override",
  } as const;
  assert.throws(
    () =>
      parsePortfolioReviewHandoffMarker(
        { ...portfolioReviewHandoff, final_system_disposition: "deep_research" },
        {
          decision: deepResearchDecision,
          thesisVersion: { ...thesis, final_disposition: "deep_research" },
          readinessResult: {
            ...readiness,
            final_disposition: "deep_research",
            readiness_status: "blocked",
          },
        },
      ),
    /requires accepted handoff decision|requires decision-ready disposition/,
  );
});

test("handoff marker cannot contain sizing, allocation, trade, order, or suitability output", () => {
  const decision = parseOperatorDecisionEvent(decisionReadyHandoff, upstream);
  for (const field of [
    "position_size",
    "share_quantity",
    "allocation",
    "trade_action",
    "order_id",
    "portfolio_suitability",
  ]) {
    assert.throws(
      () =>
        parsePortfolioReviewHandoffMarker(
          { ...portfolioReviewHandoff, [field]: "prohibited" },
          { decision, thesisVersion: thesis, readinessResult: readiness },
        ),
      /invalid portfolio review handoff marker fields/,
    );
  }
});

test("reuses identical event and side-effect replay without duplicating state", () => {
  const decision = parseOperatorDecisionEvent(decisionReadyHandoff, upstream);
  const marker = parsePortfolioReviewHandoffMarker(portfolioReviewHandoff, {
    decision,
    thesisVersion: thesis,
    readinessResult: readiness,
  });
  const deepDecision = parseOperatorDecisionEvent(
    {
      ...decisionReadyHandoff,
      operator_decision_id: "50000000-0000-4000-8000-000000000003",
      operator_action: "request_deep_research",
      relationship: "override",
      rationale: "Collect another financing filing before portfolio fit.",
      idempotency_key: "decision:operator-a:rxrx:thesis-v1:deep-research",
      created_at: "2026-05-06T22:07:30Z",
    },
    upstream,
  );
  const command = parseOperatorWorkflowCommand(deepResearchCommand, {
    decision: deepDecision,
  });

  assert.deepEqual(resolveOperatorDecisionReplay([], decision), {
    outcome: "created",
    value: decision,
  });
  assert.deepEqual(
    resolveOperatorDecisionReplay([decision], structuredClone(decision)),
    { outcome: "reused", value: decision },
  );
  assert.deepEqual(
    resolveOperatorWorkflowCommandReplay([command], structuredClone(command)),
    { outcome: "reused", value: command },
  );
  assert.deepEqual(
    resolvePortfolioReviewHandoffReplay([marker], structuredClone(marker)),
    { outcome: "reused", value: marker },
  );
  assert.throws(
    () =>
      resolveOperatorDecisionReplay([decision], {
        ...decision,
        rationale: "Conflicting replay.",
      }),
    /operator decision idempotency collision/,
  );
});

test("rejects broken supersession chains and duplicate event identities", () => {
  const first = parseOperatorDecisionEvent(decisionReadyHandoff, upstream);
  const second = {
    ...first,
    operator_decision_id: "50000000-0000-4000-8000-000000000002",
    operator_action: "no_action",
    relationship: "defer",
    idempotency_key: "decision:operator-a:rxrx:thesis-v1:defer",
    created_at: "2026-05-06T22:06:00Z",
  } as const;
  const history = {
    contract_version: "operator_decision_history.v1",
    operator_id: first.operator_id,
    security_id: first.security_id,
    thesis_contract_id: first.thesis_contract_id,
    events: [first, second],
    generated_at: "2026-05-06T22:07:00Z",
  };

  assert.throws(
    () => parseOperatorDecisionHistory(history, upstream),
    /invalid operator decision supersession chain/,
  );
  assert.throws(
    () =>
      parseOperatorDecisionHistory(
        {
          ...history,
          events: [
            first,
            {
              ...first,
              supersedes_operator_decision_id: first.operator_decision_id,
              created_at: "2026-05-06T22:06:00Z",
            },
          ],
        },
        upstream,
      ),
    /duplicate operator decision id|duplicate operator decision idempotency key/,
  );
});

test("does not create a research command for any non-deep-research action", () => {
  const handoffDecision = parseOperatorDecisionEvent(decisionReadyHandoff, upstream);
  assert.throws(
    () =>
      parseOperatorWorkflowCommand(
        {
          ...deepResearchCommand,
          operator_decision_id: handoffDecision.operator_decision_id,
        },
        { decision: handoffDecision },
      ),
    /requires deep-research decision/,
  );
});

test("publishes strict operator-decision schemas and package-root exports", () => {
  const publicTypes = readFileSync(new URL("./index.ts", import.meta.url), "utf8");
  const schema = JSON.parse(
    readFileSync(new URL("./operator-decision.schema.json", import.meta.url), "utf8"),
  ) as Record<string, any>;

  assert.match(publicTypes, /parseOperatorDecisionEvent/);
  assert.match(publicTypes, /deriveOperatorDecisionRelationship/);
  assert.match(publicTypes, /parseOperatorWorkflowCommand/);
  assert.match(publicTypes, /parsePortfolioReviewHandoffMarker/);
  assert.equal(schema.$schema, "https://json-schema.org/draft/2020-12/schema");
  assert.equal(
    schema.$defs.operator_decision_event.properties.contract_version.const,
    "operator_decision_event.v1",
  );
  assert.equal(schema.$defs.operator_decision_event.additionalProperties, false);
  assert.deepEqual(schema.$defs.thesis_contract_id.enum, [
    "biotech_moonshot_catalyst_assessment",
    "biotech_moonshot_catalyst_personal_research_v1",
  ]);
  assert.equal(
    schema.$defs.portfolio_review_handoff_marker.properties.thesis_contract_id
      .$ref,
    "#/$defs/strict_thesis_contract_id",
  );
  assert.match(
    JSON.stringify(schema.$defs.operator_decision_event.allOf),
    /biotech_moonshot_catalyst_personal_research_v1.*mark_for_future_portfolio_review/,
  );
  assert.equal(schema.$defs.operator_workflow_command.additionalProperties, false);
  assert.equal(
    schema.$defs.portfolio_review_handoff_marker.additionalProperties,
    false,
  );
  assert.doesNotMatch(
    JSON.stringify(schema.$defs.portfolio_review_handoff_marker),
    /position_size|share_quantity|allocation|trade_action|order_id|portfolio_suitability/,
  );
});
