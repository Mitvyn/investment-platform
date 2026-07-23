import type { CommitteeMemo } from "../../../packages/types/committee-memo.ts";
import type { CommitteeState } from "../../../packages/types/committee.ts";
import type { EvidenceBundle } from "../../../packages/types/evidence-bundle.ts";
import {
  parseReadinessGateResult,
  parseThesisChain,
  parseThesisCreationResult,
  parseThesisVersion,
  type ReadinessGateResult,
  type ThesisChain,
  type ThesisCreationResult,
  type ThesisVersion,
} from "../../../packages/types/readiness-thesis.ts";
import type { ResearchRun } from "../../../packages/types/research-run.ts";

import {
  createReadinessThesisLoader,
  type ReadinessViewRow,
  type ResearchRunThesisViewRow,
  type ThesisChainViewRow,
} from "./readiness-thesis-loader.ts";

const READINESS_FIELDS = [
  "operator_id",
  "research_run_id",
  "committee_result_id",
  "committee_memo_id",
  "canonical_readiness",
].join(",");
const THESIS_FIELDS = [
  "operator_id",
  "research_run_id",
  "readiness_gate_result_id",
  "creation_outcome",
  "canonical_creation_result",
  "canonical_thesis",
].join(",");
const CHAIN_FIELDS = [
  "operator_id",
  "security_id",
  "thesis_contract_id",
  "canonical_chain",
].join(",");

async function fetchReadinessRows(
  operatorId: string,
  researchRunId: string,
): Promise<ReadinessViewRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_research_run_readiness")
    .select(READINESS_FIELDS)
    .eq("operator_id", operatorId)
    .eq("research_run_id", researchRunId)
    .limit(2);
  if (error) throw new Error(`Readiness API failed: ${error.message}`);
  return (data ?? []) as unknown as ReadinessViewRow[];
}

async function fetchResearchRunThesisRows(
  operatorId: string,
  researchRunId: string,
): Promise<ResearchRunThesisViewRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_research_run_thesis")
    .select(THESIS_FIELDS)
    .eq("operator_id", operatorId)
    .eq("research_run_id", researchRunId)
    .limit(2);
  if (error) throw new Error(`Thesis API failed: ${error.message}`);
  return (data ?? []) as unknown as ResearchRunThesisViewRow[];
}

async function fetchThesisChainRows(
  operatorId: string,
  securityId: string,
  thesisContractId: string,
): Promise<ThesisChainViewRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_thesis_chains")
    .select(CHAIN_FIELDS)
    .eq("operator_id", operatorId)
    .eq("security_id", securityId)
    .eq("thesis_contract_id", thesisContractId)
    .limit(2);
  if (error) throw new Error(`Thesis Chain API failed: ${error.message}`);
  return (data ?? []) as unknown as ThesisChainViewRow[];
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map(
      (key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`,
    ).join(",")}}`;
  }
  return JSON.stringify(value);
}

export async function loadReadinessThesis(
  operatorId: string,
  upstream: {
    run: ResearchRun;
    bundle: EvidenceBundle;
    committee: CommitteeState;
    memo: CommitteeMemo;
    allowedReferenceIds: readonly string[];
  },
) {
  const { run, bundle, committee, memo } = upstream;
  return createReadinessThesisLoader<
    ReadinessGateResult,
    ThesisCreationResult,
    ThesisVersion,
    ThesisChain
  >(
    fetchReadinessRows,
    fetchResearchRunThesisRows,
    fetchThesisChainRows,
    (value, row) => parseReadinessGateResult(value, {
      operatorId,
      securityId: run.security_id,
      thesisContractId: run.thesis_contract_id,
      researchRunId: run.id,
      evidenceBundleId: bundle.id,
      evidenceBundleHash: bundle.bundle_hash,
      validatedGraderOpinionIds: committee.grader_results.flatMap((result) =>
        result.execution_state === "accepted" && result.opinion !== null
          ? [result.opinion.opinion_id]
          : [],
      ),
      committeeResultId: row.committee_result_id,
      committeeMemoId: row.committee_memo_id,
      committeeStatus: committee.committee_status,
      requestedDisposition: memo.requested_disposition,
      allowedReferenceIds: upstream.allowedReferenceIds,
    }),
    (value, _row, readiness, thesis) => parseThesisCreationResult(value, {
      readinessResult: readiness,
      thesisVersion: thesis,
    }),
    (value, _row, readiness, chain) => {
      if (chain === null) {
        throw new TypeError("Created thesis is missing ownership chain");
      }
      const raw = value as { thesis_version_id?: unknown };
      const chainVersion = [
        ...chain.canonical_versions,
        ...chain.provisional_branches,
      ].find((version) => version.thesis_version_id === raw.thesis_version_id);
      if (!chainVersion) {
        throw new TypeError("Created thesis is missing from ownership chain");
      }
      const parsed = parseThesisVersion(value, {
        readinessResult: readiness,
        questionTypeVersion: run.question_type_version,
        workflowConfigVersion: committee.workflow_config_version,
        propositionId: committee.proposition_id,
        propositionVersion: committee.proposition_version,
        memoStatementIds: memo.statements.map((statement) => statement.statement_id),
        memoDisagreementIds: memo.disagreement_records.map(
          (disagreement) => disagreement.disagreement_id,
        ),
        expectedPreviousCanonicalThesisVersionId:
          chainVersion.previous_canonical_thesis_version_id,
        expectedBasedOnThesisVersionId:
          chainVersion.based_on_thesis_version_id,
      });
      if (canonicalJson(parsed) !== canonicalJson(chainVersion)) {
        throw new TypeError("Research Run thesis does not match ownership chain");
      }
      return parsed;
    },
    (value) => parseThesisChain(value, {
      operatorId,
      securityId: run.security_id,
      thesisContractId: run.thesis_contract_id,
    }),
  )(
    operatorId,
    run.id,
    run.security_id,
    run.thesis_contract_id,
  ) as Promise<{
    readiness: Awaited<ReturnType<typeof parseReadinessGateResult>> | null;
    creation: Awaited<ReturnType<typeof parseThesisCreationResult>> | null;
    thesis: ThesisVersion | null;
    chain: Awaited<ReturnType<typeof parseThesisChain>> | null;
  }>;
}
