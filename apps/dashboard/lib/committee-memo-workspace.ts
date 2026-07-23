import type {
  CommitteeMemo,
  CommitteeMemoProvenanceType,
  CommitteeMemoStatement,
} from "../../../packages/types/committee-memo.ts";

const PROVENANCE_LABELS: Record<CommitteeMemoProvenanceType, string> = {
  fact: "Fact",
  grader_interpretation: "Grader interpretation",
  synthesis_interpretation: "Synthesis interpretation",
  assumption: "Assumption",
  gap: "Gap",
};

const GRADER_LABELS = {
  moonshot: "Moonshot",
  catalyst: "Catalyst",
  biotech: "Biotech",
  risk_dilution: "Risk / Dilution",
  valuation: "Valuation",
} as const;

function titleCase(value: string) {
  return value
    .split("_")
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function sentenceCase(value: string) {
  const normalized = value.replaceAll("_", " ");
  return `${normalized.slice(0, 1).toUpperCase()}${normalized.slice(1)}`;
}

function formatCount(value: number) {
  return value.toLocaleString("en");
}

function presentUsage(value: {
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  uncached_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  usage_complete: boolean;
}) {
  return {
    inputTokens: formatCount(value.input_tokens),
    cachedInputTokens: formatCount(value.cached_input_tokens),
    cacheWriteTokens: formatCount(value.cache_write_tokens),
    uncachedInputTokens: formatCount(value.uncached_input_tokens),
    outputTokens: formatCount(value.output_tokens),
    reasoningTokens: formatCount(value.reasoning_tokens),
    totalTokens: formatCount(value.total_tokens),
    completeness: value.usage_complete ? "Complete" : "Incomplete",
  };
}

function presentStatement(statement: CommitteeMemoStatement) {
  return {
    id: statement.statement_id,
    text: statement.text,
    provenanceCode: statement.provenance_type,
    provenanceType: PROVENANCE_LABELS[statement.provenance_type],
    evidenceIds: statement.evidence_ids,
    opinionIds: statement.opinion_ids,
    calculationIds: statement.calculation_ids,
  };
}

export function presentCommitteeMemoWorkspace(memo: CommitteeMemo | null) {
  if (memo === null) {
    return {
      kind: "missing" as const,
      title: "Committee memo unavailable",
      description:
        "No accepted provenance-valid synthesis is stored for this committee.",
    };
  }

  const statements = new Map(
    memo.statements.map((statement) => [
      statement.statement_id,
      presentStatement(statement),
    ]),
  );
  const resolve = (id: string) => {
    const statement = statements.get(id);
    if (!statement) {
      throw new TypeError(`Committee memo statement ${id} is unavailable`);
    }
    return statement;
  };
  const resolveMany = (ids: readonly string[]) => ids.map(resolve);

  return {
    kind: "ready" as const,
    identity: {
      memoId: memo.memo_id,
      synthesisExecutionId: memo.synthesis_execution_id,
      committeeId: memo.committee_id,
      evidenceBundleId: memo.evidence_bundle_id,
      evidenceBundleHash: memo.evidence_bundle_hash,
      contractVersion: memo.contract_version,
    },
    requestedDisposition: sentenceCase(memo.requested_disposition),
    executiveSummary: resolveMany(memo.executive_summary_statement_ids),
    commonGround: resolveMany(memo.common_ground_statement_ids),
    disagreements: memo.disagreement_records.map((record) => ({
      id: record.disagreement_id,
      disputedQuestion: resolve(record.disputed_question_statement_id),
      positions: resolveMany(record.position_statement_ids),
      contributingOpinionIds: record.contributing_opinion_ids,
      affectsDisposition: record.affects_disposition,
      resolvingEvidence: resolveMany(record.resolving_evidence_statement_ids),
    })),
    disputedAssumptions: resolveMany(
      memo.disputed_assumption_statement_ids,
    ),
    evidenceGaps: resolveMany(memo.evidence_gap_statement_ids),
    invalidations: resolveMany(memo.invalidation_statement_ids),
    requiredNextEvidence: resolveMany(
      memo.required_next_evidence_statement_ids,
    ),
    reviewTrigger: {
      type: titleCase(memo.review_trigger.trigger_type),
      reviewAt: memo.review_trigger.review_at,
      statement: resolve(memo.review_trigger.statement_id),
    },
    states: memo.state_disclosure.map((state) => ({
      graderId: state.grader_id,
      graderLabel: GRADER_LABELS[state.grader_id],
      executionState: titleCase(state.execution_state),
      opinionId: state.opinion_id,
      stance: state.stance === null ? "No stance" : titleCase(state.stance),
    })),
    validationState: "Accepted" as const,
    retryState:
      memo.execution_metadata.attempt_count === 1
        ? "No repair retry"
        : "Accepted after one repair retry",
    execution: {
      attemptCount: memo.execution_metadata.attempt_count,
      configuration: {
        promptVersion: memo.execution_metadata.prompt_version,
        modelConfigId: memo.execution_metadata.model_config_id,
        provider: memo.execution_metadata.provider,
        model: memo.execution_metadata.model,
        priceCard: memo.execution_metadata.price_card_version,
        retryPolicy: memo.execution_metadata.retry_policy_version,
      },
      usage: presentUsage(memo.execution_metadata),
      estimatedCost: `USD ${memo.execution_metadata.estimated_cost_usd}`,
      startedAt: memo.execution_metadata.started_at,
      completedAt: memo.execution_metadata.completed_at,
      createdAt: memo.created_at,
      attempts: memo.execution_metadata.attempts.map((attempt) => ({
        id: attempt.attempt_id,
        number: attempt.attempt_number,
        status:
          attempt.result === "accepted"
            ? { label: "Accepted" as const, variant: "verified" as const }
            : { label: "Validation error" as const, variant: "destructive" as const },
        providerRequestId: attempt.provider_request_id,
        validation:
          attempt.validation_status === "passed"
            ? { label: "Passed" as const, variant: "verified" as const, errors: attempt.validation_errors }
            : { label: "Failed" as const, variant: "destructive" as const, errors: attempt.validation_errors },
        retryReason: attempt.retry_reason,
        startedAt: attempt.started_at,
        completedAt: attempt.completed_at,
        duration: `${formatCount(attempt.duration_ms)} ms`,
        usage: presentUsage(attempt),
        estimatedCost: `USD ${attempt.estimated_cost_usd}`,
      })),
    },
  };
}

export type CommitteeMemoPresentation = ReturnType<
  typeof presentCommitteeMemoWorkspace
>;
