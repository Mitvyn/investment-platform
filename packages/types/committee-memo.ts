import type {
  CommitteeExecutionState,
  CommitteeGraderId,
  CommitteeStance,
  CommitteeStatus,
} from "./committee.ts";

export type CommitteeMemoProvenanceType =
  | "fact"
  | "grader_interpretation"
  | "synthesis_interpretation"
  | "assumption"
  | "gap";

export type ResearchDisposition =
  | "reject"
  | "monitor"
  | "deep_research"
  | "decision_ready";

export type CommitteeMemoStatement = {
  statement_id: string;
  text: string;
  provenance_type: CommitteeMemoProvenanceType;
  evidence_ids: string[];
  opinion_ids: string[];
  calculation_ids: string[];
};

export type CommitteeMemoDisagreement = {
  disagreement_id: string;
  disputed_question_statement_id: string;
  position_statement_ids: string[];
  contributing_opinion_ids: string[];
  affects_disposition: boolean;
  resolving_evidence_statement_ids: string[];
};

export type CommitteeMemoStateDisclosure = {
  grader_id: CommitteeGraderId;
  execution_state: CommitteeExecutionState;
  opinion_id: string | null;
  stance: CommitteeStance | null;
};

export type CommitteeMemoSynthesisAttempt = {
  attempt_id: string;
  attempt_number: 1 | 2;
  provider_request_id: string;
  result: "validation_error" | "accepted";
  validation_status: "failed" | "passed";
  validation_errors: string[];
  retry_reason: string | null;
  started_at: string;
  completed_at: string;
  duration_ms: number;
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  uncached_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  usage_complete: boolean;
  estimated_cost_usd: string;
};

export type CommitteeMemoExecutionMetadata = {
  prompt_version: string;
  model_config_id: string;
  provider: string;
  model: string;
  attempt_count: number;
  provider_request_ids: string[];
  attempts: CommitteeMemoSynthesisAttempt[];
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  uncached_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  usage_complete: boolean;
  estimated_cost_usd: string;
  price_card_version: string;
  retry_policy_version: string;
  started_at: string;
  completed_at: string;
};

export type CommitteeMemo = {
  contract_version: "committee_memo.v1";
  memo_id: string;
  synthesis_execution_id: string;
  committee_id: string;
  research_run_id: string;
  evidence_bundle_id: string;
  evidence_bundle_hash: string;
  workflow_config_version: string;
  proposition_id: string;
  proposition_version: string;
  committee_status: CommitteeStatus;
  requested_disposition: ResearchDisposition;
  executive_summary_statement_ids: string[];
  statements: CommitteeMemoStatement[];
  common_ground_statement_ids: string[];
  disagreement_records: CommitteeMemoDisagreement[];
  disputed_assumption_statement_ids: string[];
  evidence_gap_statement_ids: string[];
  invalidation_statement_ids: string[];
  required_next_evidence_statement_ids: string[];
  review_trigger: {
    trigger_type: "date" | "evidence_event";
    review_at: string | null;
    statement_id: string;
  };
  state_disclosure: CommitteeMemoStateDisclosure[];
  execution_metadata: CommitteeMemoExecutionMetadata;
  created_at: string;
};

export type CommitteeMemoValidationContext = {
  committeeId: string;
  researchRunId: string;
  evidenceBundleId: string;
  evidenceBundleHash: string;
  workflowConfigVersion: string;
  propositionId: string;
  propositionVersion: string;
  committeeStatus: CommitteeStatus;
  evidenceIds: readonly string[];
  calculationIds: readonly string[];
  graderResults: readonly {
    graderId: CommitteeGraderId;
    executionState: CommitteeExecutionState;
    opinionId: string | null;
    stance: CommitteeStance | null;
  }[];
};

const MEMO_KEYS = [
  "contract_version", "memo_id", "synthesis_execution_id", "committee_id",
  "research_run_id", "evidence_bundle_id", "evidence_bundle_hash",
  "workflow_config_version", "proposition_id", "proposition_version",
  "committee_status", "requested_disposition", "executive_summary_statement_ids",
  "statements", "common_ground_statement_ids", "disagreement_records",
  "disputed_assumption_statement_ids", "evidence_gap_statement_ids",
  "invalidation_statement_ids", "required_next_evidence_statement_ids",
  "review_trigger", "state_disclosure", "execution_metadata", "created_at",
] as const;

const STATEMENT_KEYS = [
  "statement_id", "text", "provenance_type", "evidence_ids", "opinion_ids",
  "calculation_ids",
] as const;

const EXECUTION_METADATA_KEYS = [
  "prompt_version", "model_config_id", "provider", "model", "attempt_count",
  "provider_request_ids", "attempts", "input_tokens", "cached_input_tokens",
  "cache_write_tokens", "uncached_input_tokens", "output_tokens", "total_tokens",
  "reasoning_tokens", "usage_complete",
  "estimated_cost_usd", "price_card_version", "retry_policy_version",
  "started_at", "completed_at",
] as const;

const SYNTHESIS_ATTEMPT_KEYS = [
  "attempt_id", "attempt_number", "provider_request_id", "result",
  "validation_status", "validation_errors", "retry_reason", "started_at",
  "completed_at", "duration_ms", "input_tokens", "cached_input_tokens",
  "cache_write_tokens", "uncached_input_tokens", "output_tokens",
  "reasoning_tokens", "total_tokens", "usage_complete", "estimated_cost_usd",
] as const;

const DISAGREEMENT_KEYS = [
  "disagreement_id", "disputed_question_statement_id", "position_statement_ids",
  "contributing_opinion_ids", "affects_disposition",
  "resolving_evidence_statement_ids",
] as const;

const REVIEW_TRIGGER_KEYS = [
  "trigger_type", "review_at", "statement_id",
] as const;

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError(`invalid ${label}`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
  label: string,
) {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (
    actual.length !== expected.length ||
    actual.some((key, index) => key !== expected[index])
  ) {
    throw new TypeError(`invalid ${label} fields`);
  }
}

function stringArray(value: unknown, label: string): string[] {
  if (
    !Array.isArray(value) ||
    value.some((item) => typeof item !== "string" || item.length === 0)
  ) {
    throw new TypeError(`invalid ${label}`);
  }
  return value;
}

function sameUniqueStrings(left: readonly string[], right: readonly string[]) {
  return (
    new Set(left).size === left.length &&
    new Set(right).size === right.length &&
    [...left].sort().join("\u0000") === [...right].sort().join("\u0000")
  );
}

function decimalEqualsSum(total: string, values: readonly string[]) {
  const decimals = [total, ...values].map((value) => value.split(".")[1]?.length ?? 0);
  const scale = Math.max(...decimals);
  const integer = (value: string) => {
    const [whole, fraction = ""] = value.split(".");
    return BigInt(`${whole}${fraction.padEnd(scale, "0")}`);
  };
  return integer(total) === values.reduce(
    (sum, value) => sum + integer(value),
    BigInt(0),
  );
}

export function parseCommitteeMemo(
  value: unknown,
  context: CommitteeMemoValidationContext,
): CommitteeMemo {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError("invalid committee memo");
  }
  const memo = value as Record<string, unknown>;
  exactKeys(memo, MEMO_KEYS, "committee memo");
  if (memo.contract_version !== "committee_memo.v1") {
    throw new TypeError("invalid committee memo contract version");
  }
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  if (
    [
      memo.memo_id,
      memo.synthesis_execution_id,
      memo.committee_id,
      memo.research_run_id,
      memo.evidence_bundle_id,
    ].some((candidate) => typeof candidate !== "string" || !uuidPattern.test(candidate)) ||
    typeof memo.evidence_bundle_hash !== "string" ||
    !/^[0-9a-f]{64}$/.test(memo.evidence_bundle_hash) ||
    typeof memo.created_at !== "string" ||
    Number.isNaN(Date.parse(memo.created_at))
  ) {
    throw new TypeError("invalid committee memo identity or timestamp");
  }
  if (
    !["reject", "monitor", "deep_research", "decision_ready"].includes(
      memo.requested_disposition as string,
    )
  ) {
    throw new TypeError("invalid requested disposition");
  }
  const identityMatches =
    memo.committee_id === context.committeeId &&
    memo.research_run_id === context.researchRunId &&
    memo.evidence_bundle_id === context.evidenceBundleId &&
    memo.evidence_bundle_hash === context.evidenceBundleHash &&
    memo.workflow_config_version === context.workflowConfigVersion &&
    memo.proposition_id === context.propositionId &&
    memo.proposition_version === context.propositionVersion &&
    memo.committee_status === context.committeeStatus;
  if (!identityMatches) throw new TypeError("committee memo identity mismatch");
  if (!Array.isArray(memo.statements)) throw new TypeError("invalid statements");
  const allowedEvidence = new Set(context.evidenceIds);
  const allowedOpinions = new Set(
    context.graderResults.flatMap((result) =>
      result.opinionId === null ? [] : [result.opinionId],
    ),
  );
  const allowedCalculations = new Set(context.calculationIds);
  const statementsById = new Map<string, CommitteeMemoStatement>();
  memo.statements.forEach((candidate, index) => {
    const statement = record(candidate, `statements[${index}]`);
    exactKeys(statement, STATEMENT_KEYS, "statement");
    if (typeof statement.statement_id !== "string" || statement.statement_id.length === 0) {
      throw new TypeError(`invalid statements[${index}].statement_id`);
    }
    if (typeof statement.text !== "string" || statement.text.length === 0) {
      throw new TypeError(`invalid statements[${index}].text`);
    }
    if (
      /\b(?:target price|price target|position size|share quantity|weighted score|universal score|majority vote|confidence averaging)\b|\brecommend(?:s|ed|ing|ation)?\b.{0,20}\b(?:buy|sell|trade|short|order)\b|\b(?:buy|sell|trade|short|order)\b.{0,20}\brecommendation\b/i.test(
        statement.text,
      )
    ) {
      throw new TypeError("prohibited synthesizer output");
    }
    if (statementsById.has(statement.statement_id)) {
      throw new TypeError("invalid memo section provenance: duplicate statement identity");
    }
    const evidenceIds = stringArray(statement.evidence_ids, `statements[${index}].evidence_ids`);
    const opinionIds = stringArray(statement.opinion_ids, `statements[${index}].opinion_ids`);
    const calculationIds = stringArray(statement.calculation_ids, `statements[${index}].calculation_ids`);
    if (
      new Set(evidenceIds).size !== evidenceIds.length ||
      new Set(opinionIds).size !== opinionIds.length ||
      new Set(calculationIds).size !== calculationIds.length
    ) {
      throw new TypeError("duplicate statement provenance reference");
    }
    for (const id of evidenceIds) {
      if (!allowedEvidence.has(id)) {
        throw new TypeError(`unresolved evidence reference ${id}`);
      }
    }
    for (const id of opinionIds) {
      if (!allowedOpinions.has(id)) {
        throw new TypeError(`unresolved opinion reference ${id}`);
      }
    }
    for (const id of calculationIds) {
      if (!allowedCalculations.has(id)) {
        throw new TypeError(`unresolved calculation reference ${id}`);
      }
    }
    const provenance = statement.provenance_type;
    const validSupport =
      (provenance === "fact" && evidenceIds.length > 0 && opinionIds.length === 0) ||
      (provenance === "grader_interpretation" && opinionIds.length === 1) ||
      (provenance === "synthesis_interpretation" && opinionIds.length >= 2) ||
      ((provenance === "assumption" || provenance === "gap") &&
        evidenceIds.length + opinionIds.length + calculationIds.length > 0);
    if (!validSupport) {
      throw new TypeError(`invalid statement provenance support at statements[${index}]`);
    }
    statementsById.set(statement.statement_id, statement as CommitteeMemoStatement);
  });
  const requireStatements = (
    value: unknown,
    label: string,
    allowedTypes?: readonly CommitteeMemoProvenanceType[],
  ) => {
    const ids = stringArray(value, label);
    if (new Set(ids).size !== ids.length) {
      throw new TypeError("invalid memo section provenance: duplicate statement reference");
    }
    for (const id of ids) {
      const statement = statementsById.get(id);
      if (!statement || (allowedTypes && !allowedTypes.includes(statement.provenance_type))) {
        throw new TypeError(`invalid memo section provenance: ${label}`);
      }
    }
    return ids;
  };
  requireStatements(memo.executive_summary_statement_ids, "executive_summary_statement_ids");
  requireStatements(memo.common_ground_statement_ids, "common_ground_statement_ids", ["synthesis_interpretation"]);
  requireStatements(memo.disputed_assumption_statement_ids, "disputed_assumption_statement_ids", ["assumption"]);
  requireStatements(memo.evidence_gap_statement_ids, "evidence_gap_statement_ids", ["gap"]);
  requireStatements(memo.invalidation_statement_ids, "invalidation_statement_ids", ["grader_interpretation", "synthesis_interpretation"]);
  requireStatements(memo.required_next_evidence_statement_ids, "required_next_evidence_statement_ids", ["gap"]);
  if (!Array.isArray(memo.disagreement_records)) {
    throw new TypeError("invalid memo section provenance: disagreement_records");
  }
  memo.disagreement_records.forEach((candidate, index) => {
    const disagreement = record(candidate, `disagreement_records[${index}]`);
    exactKeys(disagreement, DISAGREEMENT_KEYS, "disagreement record");
    if (
      typeof disagreement.disagreement_id !== "string" ||
      disagreement.disagreement_id.length === 0 ||
      typeof disagreement.affects_disposition !== "boolean"
    ) {
      throw new TypeError("invalid disagreement record");
    }
    const questionIds = requireStatements(
      [disagreement.disputed_question_statement_id],
      `disagreement_records[${index}].disputed_question_statement_id`,
      ["synthesis_interpretation"],
    );
    const positionIds = requireStatements(
      disagreement.position_statement_ids,
      `disagreement_records[${index}].position_statement_ids`,
      ["grader_interpretation"],
    );
    if (positionIds.length < 2) {
      throw new TypeError("invalid memo section provenance: disagreement positions");
    }
    requireStatements(
      disagreement.resolving_evidence_statement_ids,
      `disagreement_records[${index}].resolving_evidence_statement_ids`,
      ["gap"],
    );
    const contributingOpinionIds = stringArray(
      disagreement.contributing_opinion_ids,
      `disagreement_records[${index}].contributing_opinion_ids`,
    );
    const statementOpinionIds = [...questionIds, ...positionIds].flatMap(
      (id) => statementsById.get(id)!.opinion_ids,
    );
    const expectedOpinionIds = [...new Set(statementOpinionIds)];
    if (!sameUniqueStrings(contributingOpinionIds, expectedOpinionIds)) {
      throw new TypeError("invalid memo section provenance: disagreement contributors");
    }
  });
  const reviewTrigger = record(memo.review_trigger, "review_trigger");
  exactKeys(reviewTrigger, REVIEW_TRIGGER_KEYS, "review trigger");
  if (
    !["date", "evidence_event"].includes(reviewTrigger.trigger_type as string) ||
    (reviewTrigger.review_at !== null &&
      (typeof reviewTrigger.review_at !== "string" ||
        Number.isNaN(Date.parse(reviewTrigger.review_at)))) ||
    (reviewTrigger.trigger_type === "date" && reviewTrigger.review_at === null) ||
    (reviewTrigger.trigger_type === "evidence_event" && reviewTrigger.review_at !== null)
  ) {
    throw new TypeError("invalid review trigger");
  }
  requireStatements([reviewTrigger.statement_id], "review_trigger.statement_id", ["gap", "assumption"]);
  const executionMetadata = record(memo.execution_metadata, "execution_metadata");
  try {
    exactKeys(
      executionMetadata,
      EXECUTION_METADATA_KEYS,
      "synthesis execution metadata",
    );
    for (const field of [
      "prompt_version", "model_config_id", "provider", "model",
      "price_card_version", "retry_policy_version", "started_at", "completed_at",
    ]) {
      if (typeof executionMetadata[field] !== "string" || executionMetadata[field] === "") {
        throw new TypeError("invalid synthesis execution metadata");
      }
    }
    const attemptCount = executionMetadata.attempt_count;
    if (!Number.isSafeInteger(attemptCount) || (attemptCount as number) < 1 || (attemptCount as number) > 2) {
      throw new TypeError("invalid synthesis execution metadata");
    }
    const requestIds = stringArray(
      executionMetadata.provider_request_ids,
      "execution_metadata.provider_request_ids",
    );
    if (!Array.isArray(executionMetadata.attempts)) {
      throw new TypeError("invalid synthesis execution metadata");
    }
    const attempts = executionMetadata.attempts.map((candidate, index) => {
      const attempt = record(candidate, `execution_metadata.attempts[${index}]`);
      exactKeys(attempt, SYNTHESIS_ATTEMPT_KEYS, "synthesis attempt");
      if (
        typeof attempt.attempt_id !== "string" ||
        !uuidPattern.test(attempt.attempt_id) ||
        attempt.attempt_number !== index + 1 ||
        typeof attempt.provider_request_id !== "string" ||
        attempt.provider_request_id.length === 0 ||
        !["validation_error", "accepted"].includes(attempt.result as string) ||
        !["failed", "passed"].includes(attempt.validation_status as string) ||
        (attempt.retry_reason !== null &&
          (typeof attempt.retry_reason !== "string" || attempt.retry_reason.length === 0)) ||
        typeof attempt.started_at !== "string" ||
        typeof attempt.completed_at !== "string" ||
        Number.isNaN(Date.parse(attempt.started_at)) ||
        Number.isNaN(Date.parse(attempt.completed_at)) ||
        Date.parse(attempt.started_at) > Date.parse(attempt.completed_at) ||
        !Number.isSafeInteger(attempt.duration_ms) ||
        (attempt.duration_ms as number) < 0 ||
        attempt.duration_ms !==
          Date.parse(attempt.completed_at) - Date.parse(attempt.started_at) ||
        typeof attempt.usage_complete !== "boolean" ||
        typeof attempt.estimated_cost_usd !== "string" ||
        !/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(attempt.estimated_cost_usd)
      ) {
        throw new TypeError("invalid synthesis execution metadata");
      }
      const validationErrors = stringArray(
        attempt.validation_errors,
        `execution_metadata.attempts[${index}].validation_errors`,
      );
      for (const field of [
        "input_tokens", "cached_input_tokens", "cache_write_tokens",
        "uncached_input_tokens", "output_tokens", "reasoning_tokens",
        "total_tokens",
      ] as const) {
        if (!Number.isSafeInteger(attempt[field]) || (attempt[field] as number) < 0) {
          throw new TypeError("invalid synthesis execution metadata");
        }
      }
      if (
        attempt.input_tokens !==
          (attempt.cached_input_tokens as number) +
            (attempt.cache_write_tokens as number) +
            (attempt.uncached_input_tokens as number) ||
        attempt.total_tokens !==
          (attempt.input_tokens as number) + (attempt.output_tokens as number) ||
        (attempt.reasoning_tokens as number) > (attempt.output_tokens as number) ||
        (attempt.result === "accepted" &&
          (attempt.validation_status !== "passed" ||
            validationErrors.length !== 0 ||
            attempt.retry_reason !== null)) ||
        (attempt.result === "validation_error" &&
          (attempt.validation_status !== "failed" ||
            validationErrors.length === 0 ||
            attempt.retry_reason === null))
      ) {
        throw new TypeError("invalid synthesis execution metadata");
      }
      return attempt as CommitteeMemoSynthesisAttempt;
    });
    if (
      requestIds.length !== attemptCount ||
      new Set(requestIds).size !== requestIds.length ||
      attempts.length !== attemptCount ||
      attempts.some((attempt, index) =>
        attempt.provider_request_id !== requestIds[index]
      ) ||
      attempts.at(-1)?.result !== "accepted" ||
      attempts.some((attempt, index) =>
        index < attempts.length - 1 && attempt.result !== "validation_error"
      )
    ) {
      throw new TypeError("invalid synthesis execution metadata");
    }
    for (const field of [
      "input_tokens", "cached_input_tokens", "cache_write_tokens",
      "uncached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens",
    ] as const) {
      const count = executionMetadata[field];
      if (!Number.isSafeInteger(count) || (count as number) < 0) {
        throw new TypeError("invalid synthesis execution metadata");
      }
    }
    if (
      executionMetadata.input_tokens !==
        (executionMetadata.cached_input_tokens as number) +
          (executionMetadata.cache_write_tokens as number) +
          (executionMetadata.uncached_input_tokens as number) ||
      executionMetadata.total_tokens !==
      (executionMetadata.input_tokens as number) +
        (executionMetadata.output_tokens as number) ||
      (executionMetadata.reasoning_tokens as number) >
        (executionMetadata.output_tokens as number) ||
      typeof executionMetadata.usage_complete !== "boolean" ||
      executionMetadata.usage_complete !==
        attempts.every((attempt) => attempt.usage_complete) ||
      [
        "input_tokens", "cached_input_tokens", "cache_write_tokens",
        "uncached_input_tokens", "output_tokens", "reasoning_tokens",
        "total_tokens",
      ].some((field) =>
        executionMetadata[field] !== attempts.reduce(
          (sum, attempt) => sum + (attempt[field as keyof CommitteeMemoSynthesisAttempt] as number),
          0,
        )
      )
    ) {
      throw new TypeError("invalid synthesis execution metadata");
    }
    if (
      typeof executionMetadata.estimated_cost_usd !== "string" ||
      !/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(executionMetadata.estimated_cost_usd)
    ) {
      throw new TypeError("invalid synthesis execution metadata");
    }
    if (
      !decimalEqualsSum(
        executionMetadata.estimated_cost_usd,
        attempts.map((attempt) => attempt.estimated_cost_usd),
      ) ||
      attempts[0]?.started_at !== executionMetadata.started_at ||
      attempts.at(-1)?.completed_at !== executionMetadata.completed_at
    ) {
      throw new TypeError("invalid synthesis execution metadata");
    }
    if (
      Number.isNaN(Date.parse(executionMetadata.started_at as string)) ||
      Number.isNaN(Date.parse(executionMetadata.completed_at as string)) ||
      Date.parse(executionMetadata.started_at as string) >
        Date.parse(executionMetadata.completed_at as string)
    ) {
      throw new TypeError("invalid synthesis execution metadata");
    }
    if (
      Date.parse(executionMetadata.completed_at as string) >
      Date.parse(memo.created_at as string)
    ) {
      throw new TypeError("invalid committee memo identity or timestamp");
    }
  } catch (error) {
    if (
      error instanceof TypeError &&
      /committee memo identity or timestamp/.test(error.message)
    ) {
      throw error;
    }
    if (error instanceof TypeError && /synthesis execution metadata/.test(error.message)) {
      throw error;
    }
    throw new TypeError("invalid synthesis execution metadata");
  }
  const expectedStateDisclosure = context.graderResults.map((result) => ({
    grader_id: result.graderId,
    execution_state: result.executionState,
    opinion_id: result.opinionId,
    stance: result.stance,
  }));
  if (
    JSON.stringify(memo.state_disclosure) !==
    JSON.stringify(expectedStateDisclosure)
  ) {
    throw new TypeError("state disclosure mismatch");
  }
  return value as CommitteeMemo;
}
