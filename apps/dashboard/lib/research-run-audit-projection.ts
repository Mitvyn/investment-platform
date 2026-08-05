import type {
  CommitteeMemo,
  CommitteeState,
  EvidenceBundle,
  GraderExecution,
  ResearchValuationSnapshot,
  ResearchRun,
} from "@iros/types";

import { presentCommitteeMemoWorkspace } from "./committee-memo-workspace.ts";
import { presentEvidenceBundleWorkspace } from "./evidence-bundle-workspace.ts";
import { presentGraderCommitteeWorkspace } from "./grader-committee-workspace.ts";
import { presentGraderExecutionWorkspace } from "./grader-execution-workspace.ts";
import {
  type OperatorDecisionData,
  presentOperatorDecisionWorkspace,
} from "./operator-decision-workspace.ts";
import {
  type ReadinessThesisData,
  presentReadinessThesisWorkspace,
} from "./readiness-thesis-workspace.ts";
import {
  presentResearchRunState,
  researchRunWorkspaceFields,
} from "./research-run-workspace.ts";
import { presentValuationSnapshotWorkspace } from "./valuation-snapshot-workspace.ts";

export type ResearchRunAuditArtifacts = {
  run: ResearchRun;
  bundle: EvidenceBundle | null;
  valuationSnapshot: ResearchValuationSnapshot | null;
  graderExecutions: GraderExecution[];
  committee: CommitteeState | null;
  memo: CommitteeMemo | null;
  readinessThesis: ReadinessThesisData;
  operatorDecisions: OperatorDecisionData;
};

function isOutsideOwnershipTuple(
  value: {
    operator_id: string;
    security_id: string;
    thesis_contract_id: string;
  },
  run: ResearchRun,
) {
  return (
    value.operator_id !== run.operator_id ||
    value.security_id !== run.security_id ||
    value.thesis_contract_id !== run.thesis_contract_id
  );
}

function assertOperatorDecisionOwnership(
  run: ResearchRun,
  data: OperatorDecisionData,
) {
  const values = [
    data.history,
    data.current,
    ...(data.history?.events ?? []),
    ...data.commands,
    ...data.handoffMarkers,
  ].filter((value) => value !== null);
  if (values.some((value) => isOutsideOwnershipTuple(value, run))) {
    throw new TypeError(
      "Operator Decision data is outside Research Run ownership tuple",
    );
  }
}

export function projectResearchRunAuditWorkspace(
  operatorId: string,
  artifacts: ResearchRunAuditArtifacts,
) {
  const { run } = artifacts;
  if (run.operator_id !== operatorId) {
    throw new TypeError("Research Run is outside requested owner scope");
  }
  assertOperatorDecisionOwnership(run, artifacts.operatorDecisions);

  const stages = {
    evidence: presentEvidenceBundleWorkspace(run, artifacts.bundle),
    valuation: presentValuationSnapshotWorkspace(
      run,
      artifacts.valuationSnapshot,
    ),
    graders: presentGraderExecutionWorkspace(
      run,
      artifacts.bundle,
      artifacts.graderExecutions,
    ),
    committee: presentGraderCommitteeWorkspace(artifacts.committee),
    memo: presentCommitteeMemoWorkspace(artifacts.memo),
    readinessThesis: presentReadinessThesisWorkspace(
      artifacts.readinessThesis,
    ),
    operatorDecisions: presentOperatorDecisionWorkspace(
      artifacts.operatorDecisions,
    ),
  };
  const auditState =
    stages.evidence.kind === "ready" &&
    stages.valuation.kind === "ready" &&
    stages.graders.kind === "ready" &&
    stages.graders.executions.length === 5 &&
    (stages.committee.status.code === "complete" ||
      stages.committee.status.code === "complete_with_abstentions") &&
    stages.memo.kind === "ready" &&
    stages.readinessThesis.kind === "ready" &&
    stages.operatorDecisions.kind === "ready"
      ? ("complete" as const)
      : ("degraded" as const);

  return {
    run,
    auditState,
    fields: researchRunWorkspaceFields(run),
    eligibility: presentResearchRunState(
      run.eligibility.eligible,
      "eligibility",
    ),
    stages,
  };
}

export type ResearchRunAuditProjection = ReturnType<
  typeof projectResearchRunAuditWorkspace
>;
