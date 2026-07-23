import assert from "node:assert/strict";
import test from "node:test";

import { presentGraderCommitteeWorkspace } from "./grader-committee-workspace.ts";

test("committee workspace always presents locked five-grader roster in contract order", () => {
  const presentation = presentGraderCommitteeWorkspace([]);

  assert.deepEqual(
    presentation.rows.map((row) => ({
      grader: row.graderId,
      question: row.ownedQuestion,
      state: row.state.label,
    })),
    [
      {
        grader: "moonshot",
        question: "Is the opportunity meaningfully asymmetric?",
        state: "Not executed",
      },
      {
        grader: "catalyst",
        question: "What event resolves uncertainty, when, and with what outcomes?",
        state: "Not executed",
      },
      {
        grader: "biotech",
        question: "Is the scientific and clinical evidence credible?",
        state: "Not executed",
      },
      {
        grader: "risk_dilution",
        question: "Can shareholders survive financially until the thesis resolves?",
        state: "Not executed",
      },
      {
        grader: "valuation",
        question: "What outcomes and assumptions justify the current or implied value?",
        state: "Not executed",
      },
    ],
  );
});

test("committee accounting keeps execution states distinct and derives degraded status", () => {
  const presentation = presentGraderCommitteeWorkspace([
    {
      grader_id: "moonshot",
      execution_state: "accepted",
      required: true,
      opinion: { stance: "supports" },
    },
    {
      grader_id: "catalyst",
      execution_state: "accepted",
      required: true,
      opinion: { stance: "mixed" },
    },
    {
      grader_id: "biotech",
      execution_state: "abstained",
      required: true,
      opinion: { stance: null },
    },
    {
      grader_id: "risk_dilution",
      execution_state: "failed",
      required: true,
      opinion: null,
    },
    {
      grader_id: "valuation",
      execution_state: "not_eligible",
      required: true,
      opinion: null,
    },
  ]);

  assert.deepEqual(presentation.counts, {
    accepted: 2,
    abstained: 1,
    eligible: 4,
    notEligible: 1,
    failed: 1,
    notExecuted: 0,
  });
  assert.deepEqual(presentation.agreement, {
    supports: 1,
    mixed: 1,
    challenges: 0,
    denominator: 2,
  });
  assert.deepEqual(presentation.status, {
    code: "incomplete_required_grader_failed",
    label: "Required grader failed",
    variant: "destructive",
  });
});

test("committee rows expose accepted opinion citations and explicit nonaccepted reasons", () => {
  const presentation = presentGraderCommitteeWorkspace([
    {
      grader_id: "moonshot",
      grader_version: "moonshot.v1",
      execution_state: "accepted",
      opinion: {
        opinion_id: "opinion-moonshot",
        owned_decision_question: "Is the opportunity meaningfully asymmetric?",
        stance: "supports",
        confidence: "medium",
        summary: "Platform upside remains conditional on clinical translation.",
        material_claims: [
          {
            claim: "Clinical catalyst can resolve translation risk.",
            evidence_ids: ["evidence-clinical", "evidence-catalyst"],
          },
        ],
        evidence_gaps: [
          {
            description: "No controlled efficacy result.",
            required_evidence: "Controlled efficacy readout.",
          },
        ],
        proposition: {
          stance_rationale: "Asymmetry and catalyst support continued research.",
        },
      },
    },
    {
      grader_id: "biotech",
      grader_version: "biotech.v1",
      execution_state: "abstained",
      opinion: {
        stance: null,
        summary: "Evidence cannot support a defensible verdict.",
        material_claims: [],
        evidence_gaps: [],
        abstention: {
          reason: "Clinical evidence is immature.",
          evidence_required: ["Controlled clinical readout"],
        },
      },
    },
    {
      grader_id: "risk_dilution",
      grader_version: "risk_dilution.v1",
      execution_state: "failed",
      opinion: null,
      failure: { final_reason: "Citation validation failed after retry." },
    },
    {
      grader_id: "valuation",
      grader_version: "valuation.v1",
      execution_state: "not_eligible",
      opinion: null,
      not_eligible: { reason: "Valuation contract does not apply." },
    },
  ]);

  const moonshot = presentation.rows[0];
  assert.equal(moonshot.stance?.label, "Supports");
  assert.equal(moonshot.summary, "Platform upside remains conditional on clinical translation.");
  assert.deepEqual(moonshot.citations, ["evidence-catalyst", "evidence-clinical"]);
  assert.deepEqual(moonshot.claims, [
    {
      claim: "Clinical catalyst can resolve translation risk.",
      evidenceIds: ["evidence-clinical", "evidence-catalyst"],
    },
  ]);
  assert.deepEqual(moonshot.gaps, [
    "No controlled efficacy result. Required: Controlled efficacy readout.",
  ]);
  assert.equal(
    moonshot.reason,
    "Asymmetry and catalyst support continued research.",
  );

  assert.equal(presentation.rows[2].stance, null);
  assert.equal(presentation.rows[2].reason, "Clinical evidence is immature.");
  assert.deepEqual(presentation.rows[2].gaps, ["Controlled clinical readout"]);
  assert.equal(
    presentation.rows[3].reason,
    "Citation validation failed after retry.",
  );
  assert.equal(presentation.rows[4].reason, "Valuation contract does not apply.");
});

test("committee workspace names shared proposition without creating a vote or score", () => {
  const presentation = presentGraderCommitteeWorkspace([]);

  assert.deepEqual(presentation.proposition, {
    id: "biotech_moonshot_catalyst_case",
    version: "biotech_moonshot_catalyst_case.v1",
    text: "As of the cutoff, the available evidence supports a credible Moonshot research case with an identifiable catalyst capable of materially resolving uncertainty.",
  });
  assert.doesNotMatch(
    JSON.stringify(presentation),
    /universal_score|weighted_score|majority_vote|target_price|trade_action|position_size/,
  );
});

test("committee with no accepted opinions remains insufficient even when every grader is ineligible", () => {
  const presentation = presentGraderCommitteeWorkspace(
    ["moonshot", "catalyst", "biotech", "risk_dilution", "valuation"].map(
      (grader_id) => ({
        grader_id,
        execution_state: "not_eligible",
        opinion: null,
        not_eligible: { reason: "Rule does not apply." },
      }),
    ),
  );

  assert.equal(presentation.status.code, "insufficient_accepted_opinions");
  assert.equal(presentation.counts.accepted, 0);
  assert.equal(presentation.counts.eligible, 0);
});
