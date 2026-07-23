import {
  READINESS_CHECK_IDS,
  type ReadinessGateResult,
  type ThesisChain,
  type ThesisCreationResult,
  type ThesisVersion,
} from "../../../packages/types/readiness-thesis.ts";

export type ReadinessThesisData = {
  readiness: ReadinessGateResult | null;
  creation: ThesisCreationResult | null;
  thesis: ThesisVersion | null;
  chain: ThesisChain | null;
};

const CHECK_LABELS = {
  committee_status_complete: "Committee status complete",
  all_eligible_graders_accepted: "All eligible graders accepted",
  zero_eligible_abstentions: "Zero eligible abstentions",
  zero_required_grader_failures: "Zero required grader failures",
  blocking_evidence_requirements_satisfied:
    "Blocking evidence requirements satisfied",
  aligned_valuation_snapshot_required: "Aligned valuation snapshot required",
  source_freshness_passed: "Source freshness passed",
  material_claims_citation_valid: "Material claims citation-valid",
  grader_decision_questions_answered: "Grader questions answered",
  material_disagreement_preserved: "Material disagreement preserved",
  thesis_required_contents_present: "Required thesis contents present",
} as const;

function sentenceCase(value: string) {
  const normalized = value.replaceAll("_", " ");
  return `${normalized.slice(0, 1).toUpperCase()}${normalized.slice(1)}`;
}

function presentVersion(version: ThesisVersion) {
  return {
    id: version.thesis_version_id,
    status: sentenceCase(version.thesis_status),
    researchRunId: version.research_run_id,
    finalDisposition: sentenceCase(version.final_disposition),
    requestedDisposition: sentenceCase(version.requested_disposition),
    previousCanonicalThesisVersionId:
      version.previous_canonical_thesis_version_id,
    basedOnThesisVersionId: version.based_on_thesis_version_id,
    evidenceBundleId: version.evidence_bundle_id,
    evidenceBundleHash: version.evidence_bundle_hash,
    committeeResultId: version.committee_result_id,
    committeeMemoId: version.committee_memo_id,
    readinessGateResultId: version.readiness_gate_result_id,
    readinessPolicyVersion: version.readiness_gate_policy_version,
    questionTypeVersion: version.question_type_version,
    workflowConfigVersion: version.workflow_config_version,
    propositionId: version.proposition_id,
    propositionVersion: version.proposition_version,
    validatedGraderOpinionIds: version.validated_grader_opinion_ids,
    content: {
      coreThesisStatementIds: version.content.core_thesis_statement_ids,
      unresolvedDisagreementIds:
        version.content.unresolved_disagreement_ids,
      invalidationStatementIds: version.content.invalidation_statement_ids,
      evidenceGapStatementIds: version.content.evidence_gap_statement_ids,
      reviewTriggerStatementId: version.content.review_trigger_statement_id,
    },
    createdAt: version.created_at,
  };
}

function presentChain(chain: ThesisChain | null) {
  return {
    activeCanonicalThesisVersionId:
      chain?.active_canonical_thesis_version_id ?? null,
    canonicalVersions: chain?.canonical_versions.map(presentVersion) ?? [],
    provisionalBranches:
      chain?.provisional_branches.map(presentVersion) ?? [],
    generatedAt: chain?.generated_at ?? null,
  };
}

export function presentReadinessThesisWorkspace(
  data: ReadinessThesisData,
) {
  const chain = presentChain(data.chain);
  if (data.readiness === null) {
    return {
      kind: "missing" as const,
      title: "Readiness result unavailable",
      description:
        "No deterministic readiness result is stored for this Research Run.",
      chain,
    };
  }
  if (data.creation === null) {
    throw new TypeError("Readiness result is missing thesis creation outcome");
  }

  const failed = new Map(
    data.readiness.failed_checks.map((check) => [check.check_id, check]),
  );
  const passed = new Map(
    data.readiness.passed_checks.map((check) => [check.check_id, check]),
  );
  const checks = READINESS_CHECK_IDS.map((checkId) => {
    const check = passed.get(checkId) ?? failed.get(checkId);
    if (!check) throw new TypeError(`Readiness check ${checkId} is unavailable`);
    return {
      id: checkId,
      label: CHECK_LABELS[checkId],
      state: passed.has(checkId) ? ("passed" as const) : ("failed" as const),
      version: check.check_version,
      reasonCode: check.reason_code,
      explanation: check.explanation,
      referenceIds: check.reference_ids,
    };
  });
  const outcome = {
    canonical_created: "Canonical thesis created",
    provisional_created: "Provisional thesis created",
    no_thesis: "No thesis created",
  }[data.creation.creation_outcome];

  return {
    kind: "ready" as const,
    readiness: {
      id: data.readiness.readiness_gate_result_id,
      status: sentenceCase(data.readiness.readiness_status),
      policyVersion: data.readiness.gate_policy_version,
      requestedDisposition: sentenceCase(data.readiness.requested_disposition),
      finalDisposition: sentenceCase(data.readiness.final_disposition),
      evaluatedAt: data.readiness.evaluated_at,
      checks,
      passedCount: data.readiness.passed_checks.length,
      failedCount: data.readiness.failed_checks.length,
      blockingReasons: data.readiness.blocking_reasons.map((reason) => ({
        code: reason.reason_code,
        checkId: reason.check_id,
        explanation: reason.explanation,
      })),
      requiredNextEvidence: data.readiness.required_next_evidence.map(
        (requirement) => ({
          id: requirement.requirement_id,
          description: requirement.description,
          affectedCheckIds: requirement.affected_check_ids,
        }),
      ),
    },
    thesis: {
      creationResultId: data.creation.thesis_creation_result_id,
      outcome,
      reasonCode: data.creation.reason_code,
      version: data.thesis === null ? null : presentVersion(data.thesis),
      createdAt: data.creation.created_at,
    },
    chain,
  };
}

export type ReadinessThesisPresentation = ReturnType<
  typeof presentReadinessThesisWorkspace
>;
