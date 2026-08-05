import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type {
  CommitteeMemo,
  CommitteeState,
  EvidenceBundle,
  GraderExecution,
  OperatorDecisionCurrentState,
  OperatorDecisionEvent,
  OperatorDecisionHistory,
  PortfolioReviewHandoffMarker,
  ReadinessGateResult,
  ResearchRun,
  ThesisChain,
  ThesisCreationResult,
  ThesisVersion,
  ValuationSnapshot,
} from "@iros/types";

import { projectResearchRunAuditWorkspace } from "./research-run-audit-projection.ts";

const run = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/research_run/v1/eligible.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as ResearchRun & {
  thesis_contract_id: "biotech_moonshot_catalyst_assessment";
};

function contractFixture<T>(path: string): T {
  return JSON.parse(
    readFileSync(
      new URL(`../../../tests/fixtures/contracts/${path}`, import.meta.url),
      "utf8",
    ),
  ) as T;
}

const bundle = contractFixture<EvidenceBundle>(
  "evidence_bundle/v1/grader-ready.json",
);
const valuationSnapshot = contractFixture<ValuationSnapshot>(
  "valuation_snapshot/v1/valid-aligned.json",
);
const baseExecution = contractFixture<GraderExecution>(
  "grader_execution/v1/accepted-moonshot.json",
);

function acceptedExecutions(): GraderExecution[] {
  const overlayNames = [
    null,
    "accepted-catalyst-overlay.json",
    "accepted-biotech-overlay.json",
    "accepted-risk-dilution-overlay.json",
    "accepted-valuation-overlay.json",
  ] as const;

  return overlayNames.map((overlayName, index) => {
    const execution = structuredClone(baseExecution) as Record<string, any>;
    if (overlayName !== null) {
      const overlay = contractFixture<Record<string, any>>(
        `grader_execution/v1/${overlayName}`,
      );
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
      execution.opinion.owned_decision_question =
        overlay.owned_decision_question;
      delete execution.opinion.moonshot_payload;
      execution.opinion[overlay.payload_key] = overlay.payload;
    }
    const suffix = String(index + 1).padStart(12, "0");
    execution.id = `10000000-0000-4000-8000-${suffix}`;
    execution.operator_id = run.operator_id;
    execution.research_run_id = run.id;
    execution.evidence_bundle_id = bundle.id;
    execution.evidence_bundle_hash = bundle.bundle_hash;
    execution.opinion.opinion_id = `20000000-0000-4000-8000-${suffix}`;
    return execution as GraderExecution;
  });
}

function completeArtifacts() {
  const executions = acceptedExecutions();
  const opinionIds = executions.map((execution) => execution.opinion!.opinion_id);
  const committeeId = "32000000-0000-4000-8000-000000000001";
  const committee = {
    contract_version: "committee_state.v1",
    research_run_id: run.id,
    evidence_bundle_id: bundle.id,
    evidence_bundle_hash: bundle.bundle_hash,
    workflow_config_version: run.workflow_config_version,
    proposition_id: "biotech_moonshot_catalyst_case",
    proposition_version: "biotech_moonshot_catalyst_case.v1",
    rendered_proposition_text:
      "As of the cutoff, the available evidence supports a credible Moonshot research case with an identifiable catalyst capable of materially resolving uncertainty.",
    committee_status: "complete",
    accounting: {
      eligible_count: 5,
      accepted_count: 5,
      abstained_count: 0,
      not_eligible_count: 0,
      failed_count: 0,
      not_executed_count: 0,
    },
    stance_counts: { supports: 5, mixed: 0, challenges: 0 },
    stance_matrix: executions.map((execution) => ({
      grader_id: execution.grader_id,
      opinion_id: execution.opinion!.opinion_id,
      stance: "supports",
      stance_rationale: `${execution.grader_id} supports the proposition.`,
    })),
    grader_results: executions.map((execution) => ({
      contract_version: "committee_grader_result.v1",
      grader_id: execution.grader_id,
      grader_version: execution.grader_version,
      grader_contract_version: execution.grader_contract_version,
      output_schema_version: execution.output_schema_version,
      required: execution.required,
      evidence_bundle_id: bundle.id,
      evidence_bundle_hash: bundle.bundle_hash,
      execution_id: execution.id,
      execution_state: execution.execution_state,
      opinion: execution.opinion,
      not_eligible: null,
      not_executed: null,
      failure: null,
      persisted_at: execution.finished_at,
    })),
    derived_at: "2026-05-06T22:02:00Z",
  } as CommitteeState;

  const memo = contractFixture<CommitteeMemo>(
    "committee_memo/v1/valid.json",
  );
  memo.committee_id = committeeId;
  memo.research_run_id = run.id;
  memo.evidence_bundle_id = bundle.id;
  memo.evidence_bundle_hash = bundle.bundle_hash;
  memo.workflow_config_version = run.workflow_config_version;
  memo.committee_status = "complete";
  memo.requested_disposition = "decision_ready";

  const readiness = contractFixture<ReadinessGateResult>(
    "readiness_thesis/v1/decision-ready.json",
  );
  readiness.operator_id = run.operator_id;
  readiness.security_id = run.security_id;
  readiness.research_run_id = run.id;
  readiness.evidence_bundle_id = bundle.id;
  readiness.evidence_bundle_hash = bundle.bundle_hash;
  readiness.validated_grader_opinion_ids = opinionIds;
  readiness.committee_result_id = committeeId;
  readiness.committee_memo_id = memo.memo_id;

  const thesis = contractFixture<ThesisVersion>(
    "readiness_thesis/v1/canonical-thesis.json",
  );
  thesis.operator_id = run.operator_id;
  thesis.security_id = run.security_id;
  thesis.research_run_id = run.id;
  thesis.evidence_bundle_id = bundle.id;
  thesis.evidence_bundle_hash = bundle.bundle_hash;
  thesis.workflow_config_version = run.workflow_config_version;
  thesis.validated_grader_opinion_ids = opinionIds;
  thesis.committee_result_id = committeeId;
  thesis.committee_memo_id = memo.memo_id;
  thesis.readiness_gate_result_id = readiness.readiness_gate_result_id;

  const creation: ThesisCreationResult = {
    contract_version: "thesis_creation_result.v1",
    thesis_creation_result_id: "42000000-0000-4000-8000-000000000001",
    operator_id: run.operator_id,
    security_id: run.security_id,
    thesis_contract_id: run.thesis_contract_id,
    research_run_id: run.id,
    committee_result_id: committeeId,
    readiness_gate_result_id: readiness.readiness_gate_result_id,
    committee_status: "complete",
    creation_outcome: "canonical_created",
    thesis_version_id: thesis.thesis_version_id,
    reason_code: "complete_committee_canonical_thesis",
    created_at: thesis.created_at,
  };
  const chain: ThesisChain = {
    contract_version: "thesis_chain.v1",
    operator_id: run.operator_id,
    security_id: run.security_id,
    thesis_contract_id: run.thesis_contract_id,
    active_canonical_thesis_version_id: thesis.thesis_version_id,
    canonical_versions: [thesis],
    provisional_branches: [],
    generated_at: thesis.created_at,
  };

  const decision = contractFixture<OperatorDecisionEvent>(
    "operator_decision/v1/decision-ready-handoff.json",
  );
  decision.operator_id = run.operator_id;
  decision.security_id = run.security_id;
  decision.thesis_version_id = thesis.thesis_version_id;
  decision.committee_result_id = committeeId;
  decision.readiness_gate_result_id = readiness.readiness_gate_result_id;
  const marker = contractFixture<PortfolioReviewHandoffMarker>(
    "operator_decision/v1/portfolio-review-handoff.json",
  );
  marker.operator_id = run.operator_id;
  marker.security_id = run.security_id;
  marker.operator_decision_id = decision.operator_decision_id;
  marker.thesis_version_id = thesis.thesis_version_id;
  marker.committee_result_id = committeeId;
  marker.readiness_gate_result_id = readiness.readiness_gate_result_id;
  const history: OperatorDecisionHistory = {
    contract_version: "operator_decision_history.v1",
    operator_id: run.operator_id,
    security_id: run.security_id,
    thesis_contract_id: run.thesis_contract_id,
    events: [decision],
    generated_at: decision.created_at,
  };
  const current: OperatorDecisionCurrentState = {
    contract_version: "operator_decision_current_state.v1",
    operator_id: run.operator_id,
    security_id: run.security_id,
    thesis_contract_id: run.thesis_contract_id,
    current_operator_decision_id: decision.operator_decision_id,
    current_operator_action: decision.operator_action,
    current_relationship: decision.relationship,
    supersession_depth: 0,
    derived_at: decision.created_at,
  };

  return {
    run,
    bundle,
    valuationSnapshot,
    graderExecutions: executions,
    committee,
    memo,
    readinessThesis: { readiness, creation, thesis, chain },
    operatorDecisions: {
      history,
      current,
      commands: [],
      handoffMarkers: [marker],
    },
  };
}

test("an owned run with missing downstream stages remains explicitly auditable", () => {
  const projection = projectResearchRunAuditWorkspace(run.operator_id, {
    run,
    bundle: null,
    valuationSnapshot: null,
    graderExecutions: [],
    committee: null,
    memo: null,
    readinessThesis: {
      readiness: null,
      creation: null,
      thesis: null,
      chain: null,
    },
    operatorDecisions: {
      history: null,
      current: null,
      commands: [],
      handoffMarkers: [],
    },
  });

  assert.equal(projection.auditState, "degraded");
  assert.equal(projection.stages.evidence.kind, "missing");
  assert.equal(projection.stages.valuation.kind, "missing");
  assert.equal(projection.stages.graders.kind, "missing");
  assert.equal(
    projection.stages.committee.status.code,
    "insufficient_accepted_opinions",
  );
  assert.deepEqual(
    projection.stages.committee.rows.map((row) => row.stateCode),
    ["not_executed", "not_executed", "not_executed", "not_executed", "not_executed"],
  );
  assert.equal(projection.stages.memo.kind, "missing");
  assert.equal(projection.stages.readinessThesis.kind, "missing");
  assert.equal(projection.stages.operatorDecisions.kind, "missing");
});

test("the aggregate projection rejects a Research Run outside owner scope", () => {
  assert.throws(
    () =>
      projectResearchRunAuditWorkspace(
        "11111111-1111-4111-8111-111111111111",
        {
          run,
          bundle: null,
          valuationSnapshot: null,
          graderExecutions: [],
          committee: null,
          memo: null,
          readinessThesis: {
            readiness: null,
            creation: null,
            thesis: null,
            chain: null,
          },
          operatorDecisions: {
            history: null,
            current: null,
            commands: [],
            handoffMarkers: [],
          },
        },
      ),
    /outside requested owner scope/,
  );
});

test("one internally consistent full workflow result projects the complete audit chain", () => {
  const projection = projectResearchRunAuditWorkspace(
    run.operator_id,
    completeArtifacts(),
  );

  assert.equal(projection.auditState, "complete");
  assert.equal(projection.stages.evidence.kind, "ready");
  assert.equal(projection.stages.valuation.kind, "ready");
  assert.equal(projection.stages.graders.kind, "ready");
  if (projection.stages.graders.kind !== "ready") return;
  assert.deepEqual(
    projection.stages.graders.executions.map(
      (execution) => execution.identity.grader,
    ),
    ["moonshot", "catalyst", "biotech", "risk_dilution", "valuation"],
  );
  assert.equal(projection.stages.committee.status.code, "complete");
  assert.equal(projection.stages.memo.kind, "ready");
  assert.equal(projection.stages.readinessThesis.kind, "ready");
  assert.equal(projection.stages.operatorDecisions.kind, "ready");
});

test("the aggregate projection rejects downstream decision data outside owner scope", () => {
  const artifacts = completeArtifacts();
  artifacts.operatorDecisions.history!.operator_id =
    "11111111-1111-4111-8111-111111111111";

  assert.throws(
    () => projectResearchRunAuditWorkspace(run.operator_id, artifacts),
    /Operator Decision data is outside Research Run ownership tuple/,
  );
});

test("the authenticated workspace consumes the generic research-only projection", () => {
  const projectionSource = readFileSync(
    new URL("./research-run-audit-projection.ts", import.meta.url),
    "utf8",
  );
  const pageSource = readFileSync(
    new URL("../app/research-runs/[runId]/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(pageSource, /projectResearchRunAuditWorkspace\(/);
  assert.doesNotMatch(`${projectionSource}\n${pageSource}`, /RXRX/);
  assert.doesNotMatch(
    JSON.stringify(
      projectResearchRunAuditWorkspace(run.operator_id, completeArtifacts()),
    ),
    /universal_score|weighted_score|target_price|trade_action|position_size|allocation/,
  );
});
