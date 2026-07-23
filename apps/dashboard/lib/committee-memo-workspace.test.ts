import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { CommitteeMemo } from "../../../packages/types/committee-memo.ts";

import { presentCommitteeMemoWorkspace } from "./committee-memo-workspace.ts";

const memo = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/committee_memo/v1/valid.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as CommitteeMemo;

test("memo workspace resolves typed statements into exact audit sections", () => {
  const presentation = presentCommitteeMemoWorkspace(memo);

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;

  assert.deepEqual(presentation.identity, {
    memoId: memo.memo_id,
    synthesisExecutionId: memo.synthesis_execution_id,
    committeeId: memo.committee_id,
    evidenceBundleId: memo.evidence_bundle_id,
    evidenceBundleHash: memo.evidence_bundle_hash,
    contractVersion: "committee_memo.v1",
  });
  assert.equal(presentation.requestedDisposition, "Deep research");
  assert.deepEqual(
    presentation.commonGround.map((statement) => ({
      id: statement.id,
      type: statement.provenanceType,
      opinionIds: statement.opinionIds,
    })),
    [
      {
        id: "statement-common-ground",
        type: "Synthesis interpretation",
        opinionIds: [
          "20000000-0000-4000-8000-000000000001",
          "20000000-0000-4000-8000-000000000002",
        ],
      },
    ],
  );
  assert.equal(
    presentation.reviewTrigger.statement.text,
    "Review when controlled efficacy results become public.",
  );
  assert.deepEqual(
    presentation.states.map((state) => ({
      grader: state.graderLabel,
      state: state.executionState,
      stance: state.stance,
    })),
    [
      { grader: "Moonshot", state: "Accepted", stance: "Supports" },
      { grader: "Catalyst", state: "Accepted", stance: "Mixed" },
      { grader: "Biotech", state: "Accepted", stance: "Challenges" },
      { grader: "Risk / Dilution", state: "Accepted", stance: "Challenges" },
      { grader: "Valuation", state: "Accepted", stance: "Mixed" },
    ],
  );
});

test("memo workspace preserves disagreement, provenance references, and retry audit", () => {
  const presentation = presentCommitteeMemoWorkspace({
    ...memo,
    execution_metadata: { ...memo.execution_metadata, attempt_count: 2 },
  });
  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;

  assert.deepEqual(presentation.disagreements[0], {
    id: "disagreement-financing-asymmetry",
    disputedQuestion: {
      id: "statement-disputed-question",
      text: "Whether financing risk preserves or erodes per-share asymmetry remains disputed.",
      provenanceCode: "synthesis_interpretation",
      provenanceType: "Synthesis interpretation",
      evidenceIds: [],
      opinionIds: [
        "20000000-0000-4000-8000-000000000001",
        "20000000-0000-4000-8000-000000000004",
      ],
      calculationIds: [],
    },
    positions: presentation.disagreements[0].positions,
    contributingOpinionIds: [
      "20000000-0000-4000-8000-000000000001",
      "20000000-0000-4000-8000-000000000004",
    ],
    affectsDisposition: true,
    resolvingEvidence: presentation.disagreements[0].resolvingEvidence,
  });
  assert.deepEqual(presentation.disputedAssumptions[0].calculationIds, [
    "calc-enterprise-value-v1",
  ]);
  assert.equal(presentation.validationState, "Accepted");
  assert.equal(presentation.retryState, "Accepted after one repair retry");
  assert.equal(presentation.execution.attemptCount, 2);
});

test("memo workspace presents complete synthesis attempt audit without provider bodies or reasoning content", () => {
  const presentation = presentCommitteeMemoWorkspace(memo);
  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;

  assert.deepEqual(presentation.execution.configuration, {
    promptVersion: "committee_reconcile_v1",
    modelConfigId: "biotech_committee_synthesizer_gpt_5_6_sol_medium_v1",
    provider: "openai",
    model: "gpt-5.6-sol",
    priceCard: "gpt_5_6_sol_usd.v1",
    retryPolicy: "grader-retry-policy-v1",
  });
  assert.deepEqual(presentation.execution.usage, {
    inputTokens: "3,200",
    cachedInputTokens: "500",
    cacheWriteTokens: "700",
    uncachedInputTokens: "2,000",
    outputTokens: "900",
    reasoningTokens: "300",
    totalTokens: "4,100",
    completeness: "Complete",
  });
  assert.deepEqual(presentation.execution.attempts[0], {
    id: "34000000-0000-4000-8000-000000000001",
    number: 1,
    status: { label: "Accepted", variant: "verified" },
    providerRequestId: "offline-request-001",
    validation: { label: "Passed", variant: "verified", errors: [] },
    retryReason: null,
    startedAt: "2026-05-06T22:03:00Z",
    completedAt: "2026-05-06T22:03:04Z",
    duration: "4,000 ms",
    usage: presentation.execution.usage,
    estimatedCost: "USD 0.000000",
  });
  assert.doesNotMatch(
    JSON.stringify(presentation.execution),
    /raw_request|raw_response|reasoning_content/,
  );
});

test("memo workspace explains missing accepted synthesis without inventing content", () => {
  assert.deepEqual(presentCommitteeMemoWorkspace(null), {
    kind: "missing",
    title: "Committee memo unavailable",
    description:
      "No accepted provenance-valid synthesis is stored for this committee.",
  });
});
