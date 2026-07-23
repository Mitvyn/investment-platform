import type { CommitteeState } from "../../../packages/types/committee.ts";
import {
  parseCommitteeMemo,
  type CommitteeMemoValidationContext,
} from "../../../packages/types/committee-memo.ts";

import {
  createCommitteeMemoLoader,
  type CommitteeMemoViewRow,
} from "./committee-memo-loader.ts";

async function fetchCommitteeMemoRows(
  operatorId: string,
  researchRunId: string,
): Promise<CommitteeMemoViewRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_research_run_committee_memos")
    .select(
      "operator_id,research_run_id,committee_result_id,memo_id,canonical_memo",
    )
    .eq("operator_id", operatorId)
    .eq("research_run_id", researchRunId)
    .limit(2);

  if (error) {
    throw new Error(`Committee Memo API failed: ${error.message}`);
  }
  return (data ?? []).map(
    (row: {
      operator_id: string;
      research_run_id: string;
      committee_result_id: string;
      canonical_memo: unknown;
    }) => ({
      operator_id: row.operator_id,
      research_run_id: row.research_run_id,
      committee_result_id: row.committee_result_id,
      canonical_memo: row.canonical_memo,
    }),
  );
}

export async function loadCommitteeMemo(
  operatorId: string,
  researchRunId: string,
  committee: CommitteeState,
  references: {
    evidenceIds: readonly string[];
    calculationIds: readonly string[];
  },
) {
  return createCommitteeMemoLoader(
    fetchCommitteeMemoRows,
    (value, row) => {
      const context: CommitteeMemoValidationContext = {
        committeeId: row.committee_result_id,
        researchRunId,
        evidenceBundleId: committee.evidence_bundle_id,
        evidenceBundleHash: committee.evidence_bundle_hash,
        workflowConfigVersion: committee.workflow_config_version,
        propositionId: committee.proposition_id,
        propositionVersion: committee.proposition_version,
        committeeStatus: committee.committee_status,
        evidenceIds: references.evidenceIds,
        calculationIds: references.calculationIds,
        graderResults: committee.grader_results.map((result) => ({
          graderId: result.grader_id,
          executionState: result.execution_state,
          opinionId: result.opinion?.opinion_id ?? null,
          stance:
            result.execution_state === "accepted"
              ? (result.opinion?.stance ?? null)
              : null,
        })),
      };
      return parseCommitteeMemo(value, context);
    },
  )(operatorId, researchRunId);
}
