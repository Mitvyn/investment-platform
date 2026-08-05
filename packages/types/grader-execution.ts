import {
  parseCommitteeDomainPayload,
  type BiotechDomainPayload,
  type CatalystDomainPayload,
  type RiskDilutionDomainPayload,
  type ValuationDomainPayload,
} from "./committee.ts";
import {
  RESEARCH_CONTRACTS,
  type ResearchQuestionType,
  type ResearchQuestionTypeVersion,
  type ResearchWorkflowConfigVersion,
  type ThesisContractId,
} from "./research-run.ts";

export type GraderExecutionState =
  | "not_executed"
  | "failed"
  | "abstained"
  | "accepted";

export type GraderStance = "supports" | "mixed" | "challenges";
export type GraderConfidence = "high" | "medium" | "low";

export type TokenUsage = {
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  uncached_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  tool_call_count: number;
  usage_complete: boolean;
};

export type ExecutionCost = {
  reserved_cost_usd: string;
  estimated_cost_usd: string;
  billed_cost_usd: string | null;
  currency: "USD";
  price_card_version: string;
};

export type PreCallGateCheck = {
  check_id:
    | "config_approved"
    | "retention_policy_approved"
    | "evaluation_release_approved"
    | "price_card_available"
    | "budget_available"
    | "token_caps_valid"
    | "operator_environment_allowed";
  passed: boolean;
  reason_code: string;
};

export type PreCallGate = {
  policy_version: string;
  status: "passed" | "blocked";
  checked_at: string;
  checks: PreCallGateCheck[];
};

export type BudgetRecord = {
  reservation_id: string | null;
  budget_policy_version: string;
  currency: "USD";
  reserved_cost_usd: string;
  reconciled_cost_usd: string | null;
  status: "not_reserved" | "reserved" | "reconciled" | "released";
};

export type AttemptValidation = {
  status: "not_run" | "passed" | "failed";
  schema_valid: boolean | null;
  citations_valid: boolean | null;
  errors: string[];
};

export type GraderAttempt = {
  attempt_id: string;
  attempt_number: 1 | 2;
  request_sha256: string;
  provider: string;
  model: string;
  model_config_id: string;
  prompt_version: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  result:
    | "transport_error"
    | "validation_error"
    | "accepted"
    | "abstained";
  provider_request_id: string | null;
  raw_payload_id: string | null;
  raw_payload_sha256: string | null;
  usage: TokenUsage;
  cost: ExecutionCost;
  validation: AttemptValidation;
  retry_reason: string | null;
};

export type MaterialClaim = {
  claim_id: string;
  claim: string;
  materiality: "high" | "medium" | "low";
  evidence_ids: string[];
};

export type ContradictingEvidence = {
  evidence_id: string;
  explanation: string;
};

export type GraderEvidenceGap = {
  gap_id: string;
  description: string;
  required_evidence: string;
};

export type SharedPropositionAssessment = {
  proposition_id: string;
  proposition_version: string;
  rendered_proposition_text: string;
  grader_stance: GraderStance | null;
  stance_rationale: string | null;
};

export type MoonshotPayload = {
  contract_version: "moonshot_grader_payload.v1";
  mission_relevance: "material" | "limited" | "none" | "indeterminate";
  asymmetry_assessment:
    | "credible"
    | "conditional"
    | "not_supported"
    | "indeterminate";
  evidence_maturity:
    | "clinical"
    | "preclinical"
    | "mixed"
    | "insufficient";
  strategic_or_societal_value:
    | "material"
    | "limited"
    | "not_supported"
    | "indeterminate";
  asymmetry_drivers: string[];
  limiting_factors: string[];
};

export type CatalystPayload = CatalystDomainPayload;
export type BiotechPayload = BiotechDomainPayload;
export type RiskDilutionPayload = RiskDilutionDomainPayload;
export type ValuationPayload = ValuationDomainPayload;

export type GraderAbstention = {
  reason_code: string;
  reason: string;
  missing_or_inadequate_evidence: string[];
  evidence_required: string[];
  confidence: GraderConfidence;
};

type GraderOpinionBase = {
  opinion_id: string;
  execution_id: string;
  grader_version: string;
  execution_state: "accepted" | "abstained";
  owned_decision_question: string;
  stance: GraderStance | null;
  confidence: GraderConfidence;
  summary: string;
  material_claims: MaterialClaim[];
  assumptions: string[];
  contradicting_evidence: ContradictingEvidence[];
  evidence_gaps: GraderEvidenceGap[];
  invalidation_signals: string[];
  proposition: SharedPropositionAssessment;
  abstention: GraderAbstention | null;
  created_at: string;
};

export type MoonshotGraderOpinion = GraderOpinionBase & {
  grader_id: "moonshot";
  moonshot_payload: MoonshotPayload;
};

export type CatalystGraderOpinion = GraderOpinionBase & {
  grader_id: "catalyst";
  catalyst_payload: CatalystPayload;
};

export type BiotechGraderOpinion = GraderOpinionBase & {
  grader_id: "biotech";
  biotech_payload: BiotechPayload;
};

export type RiskDilutionGraderOpinion = GraderOpinionBase & {
  grader_id: "risk_dilution";
  risk_dilution_payload: RiskDilutionPayload;
};

export type ValuationGraderOpinion = GraderOpinionBase & {
  grader_id: "valuation";
  valuation_payload: ValuationPayload;
};

export type GraderOpinion =
  | MoonshotGraderOpinion
  | CatalystGraderOpinion
  | BiotechGraderOpinion
  | RiskDilutionGraderOpinion
  | ValuationGraderOpinion;

export type NotExecutedDetail = {
  reason_code: string;
  reason: string;
  gate_policy_version: string;
  failed_gate_checks: string[];
};

export type FailureDetail = {
  category:
    | "execution_failure"
    | "timeout"
    | "schema_validation"
    | "citation_validation"
    | "contract_violation"
    | "unsupported_output";
  attempt_count: number;
  validation_errors: string[];
  final_reason: string;
  retry_policy_version: string;
};

type GraderExecutionBase = {
  contract_version: "grader_execution.v1";
  id: string;
  operator_id: string;
  research_run_id: string;
  evidence_bundle_id: string;
  evidence_bundle_hash: string;
  execution_key: string;
  question_type_id: ResearchQuestionType;
  question_type_version: ResearchQuestionTypeVersion;
  workflow_config_version: ResearchWorkflowConfigVersion;
  thesis_contract_id: ThesisContractId;
  grader_version: string;
  grader_contract_version: string;
  eligibility_rule_version: string;
  rubric_version: string;
  abstention_rules_version: string;
  prompt_version: string;
  model_config_id: string;
  provider: string;
  model: string;
  inference_parameter_hash: string;
  retry_policy_version: string;
  required: boolean;
  execution_state: GraderExecutionState;
  pre_call_gate: PreCallGate;
  budget: BudgetRecord;
  attempts: GraderAttempt[];
  total_usage: TokenUsage;
  total_cost: ExecutionCost;
  not_executed: NotExecutedDetail | null;
  failure: FailureDetail | null;
  started_at: string;
  finished_at: string;
};

export type GraderExecution =
  | (GraderExecutionBase & {
      grader_id: "moonshot";
      output_schema_version: "moonshot_grader_payload.v1";
      opinion: MoonshotGraderOpinion | null;
    })
  | (GraderExecutionBase & {
      grader_id: "catalyst";
      output_schema_version: "catalyst_grader_payload.v1";
      opinion: CatalystGraderOpinion | null;
    })
  | (GraderExecutionBase & {
      grader_id: "biotech";
      output_schema_version: "biotech_grader_payload.v1";
      opinion: BiotechGraderOpinion | null;
    })
  | (GraderExecutionBase & {
      grader_id: "risk_dilution";
      output_schema_version: "risk_dilution_grader_payload.v1";
      opinion: RiskDilutionGraderOpinion | null;
    })
  | (GraderExecutionBase & {
      grader_id: "valuation";
      output_schema_version: "valuation_grader_payload.v1";
      opinion: ValuationGraderOpinion | null;
    });

export type GraderExecutionValidationContext = {
  evidenceBundleId: string;
  evidenceBundleHash: string;
  evidenceIds: readonly string[];
  calculationIds?: readonly string[];
};

const EXECUTION_KEYS = [
  "contract_version", "id", "operator_id", "research_run_id",
  "evidence_bundle_id", "evidence_bundle_hash", "execution_key",
  "question_type_id", "question_type_version", "workflow_config_version",
  "thesis_contract_id", "grader_id", "grader_version",
  "grader_contract_version", "eligibility_rule_version", "rubric_version",
  "output_schema_version", "abstention_rules_version", "prompt_version",
  "model_config_id", "provider", "model", "inference_parameter_hash",
  "retry_policy_version", "required", "execution_state", "pre_call_gate",
  "budget", "attempts", "total_usage", "total_cost", "not_executed",
  "failure", "opinion", "started_at", "finished_at",
] as const;

const GATE_KEYS = ["policy_version", "status", "checked_at", "checks"] as const;
const GATE_CHECK_KEYS = ["check_id", "passed", "reason_code"] as const;
const BUDGET_KEYS = [
  "reservation_id", "budget_policy_version", "currency",
  "reserved_cost_usd", "reconciled_cost_usd", "status",
] as const;
const ATTEMPT_KEYS = [
  "attempt_id", "attempt_number", "request_sha256", "provider", "model",
  "model_config_id", "prompt_version", "started_at", "finished_at",
  "duration_ms", "result", "provider_request_id", "raw_payload_id",
  "raw_payload_sha256", "usage", "cost", "validation", "retry_reason",
] as const;
const USAGE_KEYS = [
  "input_tokens", "cached_input_tokens", "cache_write_tokens", "uncached_input_tokens",
  "output_tokens", "reasoning_tokens", "total_tokens", "tool_call_count",
  "usage_complete",
] as const;
const COST_KEYS = [
  "reserved_cost_usd", "estimated_cost_usd", "billed_cost_usd", "currency",
  "price_card_version",
] as const;
const VALIDATION_KEYS = [
  "status", "schema_valid", "citations_valid", "errors",
] as const;
const NOT_EXECUTED_KEYS = [
  "reason_code", "reason", "gate_policy_version", "failed_gate_checks",
] as const;
const FAILURE_KEYS = [
  "category", "attempt_count", "validation_errors", "final_reason",
  "retry_policy_version",
] as const;
const OPINION_BASE_KEYS = [
  "opinion_id", "execution_id", "grader_id", "grader_version",
  "execution_state", "owned_decision_question", "stance", "confidence",
  "summary", "material_claims", "assumptions", "contradicting_evidence",
  "evidence_gaps", "invalidation_signals", "proposition",
  "abstention", "created_at",
] as const;
const CLAIM_KEYS = ["claim_id", "claim", "materiality", "evidence_ids"] as const;
const CONTRADICTION_KEYS = ["evidence_id", "explanation"] as const;
const GAP_KEYS = ["gap_id", "description", "required_evidence"] as const;
const PROPOSITION_KEYS = [
  "proposition_id", "proposition_version", "rendered_proposition_text",
  "grader_stance", "stance_rationale",
] as const;
const ABSTENTION_KEYS = [
  "reason_code", "reason", "missing_or_inadequate_evidence",
  "evidence_required", "confidence",
] as const;

const GATE_CHECK_IDS = [
  "config_approved", "retention_policy_approved",
  "evaluation_release_approved", "price_card_available", "budget_available",
  "token_caps_valid", "operator_environment_allowed",
] as const;
const STANCES = ["supports", "mixed", "challenges"] as const;
const CONFIDENCES = ["high", "medium", "low"] as const;
const PROPOSITION_ID = "biotech_moonshot_catalyst_case";
const PROPOSITION_VERSION = "biotech_moonshot_catalyst_case.v1";
const PROPOSITION_TEXT = "As of the cutoff, the available evidence supports a credible Moonshot research case with an identifiable catalyst capable of materially resolving uncertainty.";

const GRADER_DEFINITIONS = {
  moonshot: {
    outputSchema: "moonshot_grader_payload.v1",
    payloadKey: "moonshot_payload",
  },
  catalyst: {
    outputSchema: "catalyst_grader_payload.v1",
    payloadKey: "catalyst_payload",
  },
  biotech: {
    outputSchema: "biotech_grader_payload.v1",
    payloadKey: "biotech_payload",
  },
  risk_dilution: {
    outputSchema: "risk_dilution_grader_payload.v1",
    payloadKey: "risk_dilution_payload",
  },
  valuation: {
    outputSchema: "valuation_grader_payload.v1",
    payloadKey: "valuation_payload",
  },
} as const;

type GraderId = keyof typeof GRADER_DEFINITIONS;

function graderDefinition(value: unknown) {
  oneOf(value, Object.keys(GRADER_DEFINITIONS), "grader_id");
  const graderId = value as GraderId;
  return { graderId, ...GRADER_DEFINITIONS[graderId] };
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError(`invalid ${label}`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[], label: string) {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new TypeError(`invalid ${label} fields`);
  }
}

function string(value: unknown, label: string) {
  if (typeof value !== "string" || value.length === 0) throw new TypeError(`invalid ${label}`);
}

function oneOf(value: unknown, options: readonly string[], label: string) {
  if (typeof value !== "string" || !options.includes(value)) throw new TypeError(`invalid ${label}`);
}

function assertResearchContractIdentity(
  execution: Record<string, unknown>,
) {
  const matches = Object.values(RESEARCH_CONTRACTS).filter(
    (contract) =>
      execution.question_type_id === contract.question_type &&
      execution.question_type_version === contract.question_type_version &&
      execution.workflow_config_version === contract.workflow_config_version &&
      execution.thesis_contract_id === contract.thesis_contract_id,
  );
  if (matches.length !== 1) {
    throw new TypeError("invalid research contract identity");
  }
}

function nullableString(value: unknown, label: string) {
  if (value !== null) string(value, label);
}

function strings(value: unknown, label: string, allowEmpty = true): string[] {
  if (!Array.isArray(value) || (!allowEmpty && value.length === 0) || value.some((item) => typeof item !== "string" || item.length === 0)) {
    throw new TypeError(`invalid ${label}`);
  }
  return value;
}

function uuid(value: unknown, label: string) {
  if (typeof value !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value)) {
    throw new TypeError(`invalid ${label}`);
  }
}

function hash(value: unknown, label: string) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) throw new TypeError(`invalid ${label}`);
}

function timestamp(value: unknown, label: string) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) || Number.isNaN(Date.parse(value))) {
    throw new TypeError(`invalid ${label}`);
  }
}

function decimal(value: unknown, label: string) {
  if (typeof value !== "string" || !/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value)) throw new TypeError(`invalid ${label}`);
}

function decimalEqualsSum(target: string, values: string[]) {
  const all = [target, ...values];
  const scale = Math.max(...all.map((value) => value.split(".")[1]?.length ?? 0));
  const units = (value: string) => {
    const [whole, fraction = ""] = value.split(".");
    return BigInt(whole + fraction.padEnd(scale, "0"));
  };
  return units(target) === values.reduce((sum, value) => sum + units(value), BigInt(0));
}

function integer(value: unknown, label: string, max?: number) {
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (max !== undefined && (value as number) > max)) {
    throw new TypeError(`invalid ${label}`);
  }
}

function boolean(value: unknown, label: string) {
  if (typeof value !== "boolean") throw new TypeError(`invalid ${label}`);
}

function parseUsage(value: unknown, label: string): TokenUsage {
  const usage = record(value, label);
  exactKeys(usage, USAGE_KEYS, label);
  for (const key of USAGE_KEYS.slice(0, 8)) integer(usage[key], `${label}.${key}`);
  boolean(usage.usage_complete, `${label}.usage_complete`);
  if (usage.input_tokens !== (usage.cached_input_tokens as number) + (usage.uncached_input_tokens as number)) throw new TypeError(`invalid ${label} input total`);
  if ((usage.cache_write_tokens as number) > (usage.uncached_input_tokens as number)) throw new TypeError(`invalid ${label} cache-write tokens`);
  if (usage.total_tokens !== (usage.input_tokens as number) + (usage.output_tokens as number)) throw new TypeError(`invalid ${label} total`);
  if ((usage.reasoning_tokens as number) > (usage.output_tokens as number)) throw new TypeError(`invalid ${label} reasoning tokens`);
  return usage as TokenUsage;
}

function parseCost(value: unknown, label: string): ExecutionCost {
  const cost = record(value, label);
  exactKeys(cost, COST_KEYS, label);
  decimal(cost.reserved_cost_usd, `${label}.reserved_cost_usd`);
  decimal(cost.estimated_cost_usd, `${label}.estimated_cost_usd`);
  if (cost.billed_cost_usd !== null) decimal(cost.billed_cost_usd, `${label}.billed_cost_usd`);
  oneOf(cost.currency, ["USD"], `${label}.currency`);
  string(cost.price_card_version, `${label}.price_card_version`);
  return cost as ExecutionCost;
}

function parseGate(value: unknown): PreCallGate {
  const gate = record(value, "pre_call_gate");
  exactKeys(gate, GATE_KEYS, "pre_call_gate");
  string(gate.policy_version, "pre_call_gate.policy_version");
  oneOf(gate.status, ["passed", "blocked"], "pre_call_gate.status");
  timestamp(gate.checked_at, "pre_call_gate.checked_at");
  if (!Array.isArray(gate.checks) || gate.checks.length !== GATE_CHECK_IDS.length) throw new TypeError("invalid pre_call_gate.checks");
  const seen = new Set<string>();
  gate.checks.forEach((candidate, index) => {
    const check = record(candidate, `pre_call_gate.checks[${index}]`);
    exactKeys(check, GATE_CHECK_KEYS, `pre_call_gate.checks[${index}]`);
    oneOf(check.check_id, GATE_CHECK_IDS, `pre_call_gate.checks[${index}].check_id`);
    boolean(check.passed, `pre_call_gate.checks[${index}].passed`);
    string(check.reason_code, `pre_call_gate.checks[${index}].reason_code`);
    if (seen.has(check.check_id as string)) throw new TypeError("duplicate pre-call gate check");
    seen.add(check.check_id as string);
  });
  if ((gate.status === "passed") !== gate.checks.every((check) => (check as Record<string, unknown>).passed === true)) throw new TypeError("invalid pre-call gate status");
  return gate as PreCallGate;
}

function parseBudget(value: unknown): BudgetRecord {
  const budget = record(value, "budget");
  exactKeys(budget, BUDGET_KEYS, "budget");
  if (budget.reservation_id !== null) uuid(budget.reservation_id, "budget.reservation_id");
  string(budget.budget_policy_version, "budget.budget_policy_version");
  oneOf(budget.currency, ["USD"], "budget.currency");
  decimal(budget.reserved_cost_usd, "budget.reserved_cost_usd");
  if (budget.reconciled_cost_usd !== null) decimal(budget.reconciled_cost_usd, "budget.reconciled_cost_usd");
  oneOf(budget.status, ["not_reserved", "reserved", "reconciled", "released"], "budget.status");
  return budget as BudgetRecord;
}

function parseAttempt(value: unknown, index: number): GraderAttempt {
  const label = `attempts[${index}]`;
  const attempt = record(value, label);
  exactKeys(attempt, ATTEMPT_KEYS, label);
  uuid(attempt.attempt_id, `${label}.attempt_id`);
  if (attempt.attempt_number !== 1 && attempt.attempt_number !== 2) throw new TypeError(`invalid ${label}.attempt_number`);
  hash(attempt.request_sha256, `${label}.request_sha256`);
  ["provider", "model", "model_config_id", "prompt_version"].forEach((key) => string(attempt[key], `${label}.${key}`));
  timestamp(attempt.started_at, `${label}.started_at`);
  timestamp(attempt.finished_at, `${label}.finished_at`);
  integer(attempt.duration_ms, `${label}.duration_ms`);
  oneOf(attempt.result, ["transport_error", "validation_error", "accepted", "abstained"], `${label}.result`);
  nullableString(attempt.provider_request_id, `${label}.provider_request_id`);
  if (attempt.raw_payload_id !== null) uuid(attempt.raw_payload_id, `${label}.raw_payload_id`);
  if (attempt.raw_payload_sha256 !== null) hash(attempt.raw_payload_sha256, `${label}.raw_payload_sha256`);
  parseUsage(attempt.usage, `${label}.usage`);
  parseCost(attempt.cost, `${label}.cost`);
  const validation = record(attempt.validation, `${label}.validation`);
  exactKeys(validation, VALIDATION_KEYS, `${label}.validation`);
  oneOf(validation.status, ["not_run", "passed", "failed"], `${label}.validation.status`);
  if (validation.schema_valid !== null) boolean(validation.schema_valid, `${label}.validation.schema_valid`);
  if (validation.citations_valid !== null) boolean(validation.citations_valid, `${label}.validation.citations_valid`);
  const validationErrors = strings(validation.errors, `${label}.validation.errors`);
  nullableString(attempt.retry_reason, `${label}.retry_reason`);
  if ((attempt.raw_payload_id === null) !== (attempt.raw_payload_sha256 === null)) throw new TypeError(`invalid ${label} raw payload reference`);
  if (attempt.result === "transport_error" && (attempt.raw_payload_id !== null || validation.status !== "not_run")) throw new TypeError(`invalid ${label} transport result`);
  if ((attempt.result === "accepted" || attempt.result === "abstained") && (attempt.raw_payload_id === null || validation.status !== "passed" || validation.schema_valid !== true || validation.citations_valid !== true || validationErrors.length !== 0)) throw new TypeError(`invalid ${label} accepted validation`);
  if (attempt.result === "validation_error" && (attempt.raw_payload_id === null || validation.status !== "failed" || validationErrors.length === 0)) throw new TypeError(`invalid ${label} failed validation`);
  return attempt as GraderAttempt;
}

function parseOpinion(value: unknown, context: GraderExecutionValidationContext): GraderOpinion {
  const opinion = record(value, "opinion");
  const definition = graderDefinition(opinion.grader_id);
  exactKeys(
    opinion,
    [...OPINION_BASE_KEYS, definition.payloadKey],
    "opinion",
  );
  uuid(opinion.opinion_id, "opinion.opinion_id");
  uuid(opinion.execution_id, "opinion.execution_id");
  string(opinion.grader_version, "opinion.grader_version");
  oneOf(opinion.execution_state, ["accepted", "abstained"], "opinion.execution_state");
  string(opinion.owned_decision_question, "opinion.owned_decision_question");
  if (opinion.stance !== null) oneOf(opinion.stance, STANCES, "opinion.stance");
  oneOf(opinion.confidence, CONFIDENCES, "opinion.confidence");
  string(opinion.summary, "opinion.summary");

  if (!Array.isArray(opinion.material_claims)) throw new TypeError("invalid opinion.material_claims");
  const allowedEvidence = new Set(context.evidenceIds);
  opinion.material_claims.forEach((candidate, index) => {
    const claim = record(candidate, `opinion.material_claims[${index}]`);
    exactKeys(claim, CLAIM_KEYS, `opinion.material_claims[${index}]`);
    string(claim.claim_id, `opinion.material_claims[${index}].claim_id`);
    string(claim.claim, `opinion.material_claims[${index}].claim`);
    oneOf(claim.materiality, ["high", "medium", "low"], `opinion.material_claims[${index}].materiality`);
    for (const evidenceId of strings(claim.evidence_ids, `opinion.material_claims[${index}].evidence_ids`, false)) {
      if (!allowedEvidence.has(evidenceId)) throw new TypeError(`unresolved evidence citation ${evidenceId}`);
    }
  });
  strings(opinion.assumptions, "opinion.assumptions");
  if (!Array.isArray(opinion.contradicting_evidence)) throw new TypeError("invalid opinion.contradicting_evidence");
  opinion.contradicting_evidence.forEach((candidate, index) => {
    const item = record(candidate, `opinion.contradicting_evidence[${index}]`);
    exactKeys(item, CONTRADICTION_KEYS, `opinion.contradicting_evidence[${index}]`);
    string(item.evidence_id, `opinion.contradicting_evidence[${index}].evidence_id`);
    string(item.explanation, `opinion.contradicting_evidence[${index}].explanation`);
    if (!allowedEvidence.has(item.evidence_id as string)) throw new TypeError(`unresolved evidence citation ${item.evidence_id}`);
  });
  if (!Array.isArray(opinion.evidence_gaps)) throw new TypeError("invalid opinion.evidence_gaps");
  opinion.evidence_gaps.forEach((candidate, index) => {
    const gap = record(candidate, `opinion.evidence_gaps[${index}]`);
    exactKeys(gap, GAP_KEYS, `opinion.evidence_gaps[${index}]`);
    ["gap_id", "description", "required_evidence"].forEach((key) => string(gap[key], `opinion.evidence_gaps[${index}].${key}`));
  });
  strings(opinion.invalidation_signals, "opinion.invalidation_signals");

  const proposition = record(opinion.proposition, "opinion.proposition");
  exactKeys(proposition, PROPOSITION_KEYS, "opinion.proposition");
  ["proposition_id", "proposition_version", "rendered_proposition_text"].forEach((key) => string(proposition[key], `opinion.proposition.${key}`));
  if (
    proposition.proposition_id !== PROPOSITION_ID ||
    proposition.proposition_version !== PROPOSITION_VERSION ||
    proposition.rendered_proposition_text !== PROPOSITION_TEXT
  ) throw new TypeError("invalid proposition identity");
  if (proposition.grader_stance !== null) oneOf(proposition.grader_stance, STANCES, "opinion.proposition.grader_stance");
  nullableString(proposition.stance_rationale, "opinion.proposition.stance_rationale");

  parseCommitteeDomainPayload(
    definition.graderId,
    opinion[definition.payloadKey],
    {
      evidenceBundleId: context.evidenceBundleId,
      evidenceBundleHash: context.evidenceBundleHash,
      evidenceIds: context.evidenceIds,
      calculationIds: context.calculationIds ?? [],
    },
  );

  if (opinion.abstention !== null) {
    const abstention = record(opinion.abstention, "opinion.abstention");
    exactKeys(abstention, ABSTENTION_KEYS, "opinion.abstention");
    string(abstention.reason_code, "opinion.abstention.reason_code");
    string(abstention.reason, "opinion.abstention.reason");
    strings(abstention.missing_or_inadequate_evidence, "opinion.abstention.missing_or_inadequate_evidence", false);
    strings(abstention.evidence_required, "opinion.abstention.evidence_required", false);
    oneOf(abstention.confidence, CONFIDENCES, "opinion.abstention.confidence");
  }
  timestamp(opinion.created_at, "opinion.created_at");

  if (opinion.execution_state === "accepted") {
    if (opinion.stance === null || proposition.grader_stance !== opinion.stance || proposition.stance_rationale === null || opinion.abstention !== null) throw new TypeError("invalid accepted opinion state");
  } else if (opinion.stance !== null || proposition.grader_stance !== null || proposition.stance_rationale !== null || opinion.abstention === null) {
    throw new TypeError("invalid abstained opinion state");
  }
  return opinion as GraderOpinion;
}

function sumUsage(attempts: GraderAttempt[]): TokenUsage {
  return attempts.reduce<TokenUsage>((sum, attempt) => ({
    input_tokens: sum.input_tokens + attempt.usage.input_tokens,
    cached_input_tokens: sum.cached_input_tokens + attempt.usage.cached_input_tokens,
    cache_write_tokens: sum.cache_write_tokens + attempt.usage.cache_write_tokens,
    uncached_input_tokens: sum.uncached_input_tokens + attempt.usage.uncached_input_tokens,
    output_tokens: sum.output_tokens + attempt.usage.output_tokens,
    reasoning_tokens: sum.reasoning_tokens + attempt.usage.reasoning_tokens,
    total_tokens: sum.total_tokens + attempt.usage.total_tokens,
    tool_call_count: sum.tool_call_count + attempt.usage.tool_call_count,
    usage_complete: sum.usage_complete && attempt.usage.usage_complete,
  }), { input_tokens: 0, cached_input_tokens: 0, cache_write_tokens: 0, uncached_input_tokens: 0, output_tokens: 0, reasoning_tokens: 0, total_tokens: 0, tool_call_count: 0, usage_complete: true });
}

export function parseGraderExecution(
  value: unknown,
  context: GraderExecutionValidationContext,
): GraderExecution {
  const execution = record(value, "grader execution");
  exactKeys(execution, EXECUTION_KEYS, "grader execution");
  oneOf(execution.contract_version, ["grader_execution.v1"], "contract_version");
  ["id", "operator_id", "research_run_id", "evidence_bundle_id"].forEach((key) => uuid(execution[key], key));
  hash(execution.evidence_bundle_hash, "evidence_bundle_hash");
  hash(execution.execution_key, "execution_key");
  [
    "question_type_id", "question_type_version", "workflow_config_version",
    "thesis_contract_id",
    "grader_version", "grader_contract_version", "eligibility_rule_version",
    "rubric_version", "output_schema_version", "abstention_rules_version",
    "prompt_version", "model_config_id", "provider", "model",
    "retry_policy_version",
  ].forEach((key) => string(execution[key], key));
  assertResearchContractIdentity(execution);
  const definition = graderDefinition(execution.grader_id);
  if (execution.output_schema_version !== definition.outputSchema) {
    throw new TypeError("invalid output schema identity");
  }
  hash(execution.inference_parameter_hash, "inference_parameter_hash");
  boolean(execution.required, "required");
  oneOf(execution.execution_state, ["not_executed", "failed", "abstained", "accepted"], "execution_state");
  timestamp(execution.started_at, "started_at");
  timestamp(execution.finished_at, "finished_at");
  if (execution.evidence_bundle_id !== context.evidenceBundleId || execution.evidence_bundle_hash !== context.evidenceBundleHash) throw new TypeError("grader execution bundle identity mismatch");

  const gate = parseGate(execution.pre_call_gate);
  const budget = parseBudget(execution.budget);
  if (!Array.isArray(execution.attempts) || execution.attempts.length > 2) throw new TypeError("invalid attempts");
  const attempts = execution.attempts.map(parseAttempt);
  attempts.forEach((attempt, index) => {
    if (attempt.attempt_number !== index + 1) throw new TypeError("attempts must be consecutively ordered");
    if (attempt.provider !== execution.provider || attempt.model !== execution.model || attempt.model_config_id !== execution.model_config_id || attempt.prompt_version !== execution.prompt_version) throw new TypeError("attempt changed pinned execution configuration");
    if (index > 0 && attempt.request_sha256 !== attempts[0].request_sha256) throw new TypeError("retry changed logical input");
  });

  const totalUsage = parseUsage(execution.total_usage, "total_usage");
  if (JSON.stringify(totalUsage) !== JSON.stringify(sumUsage(attempts))) throw new TypeError("total usage does not reconcile to attempts");
  const totalCost = parseCost(execution.total_cost, "total_cost");
  if (attempts.some((attempt) => attempt.cost.price_card_version !== totalCost.price_card_version)) throw new TypeError("attempt price card mismatch");
  if (
    totalCost.reserved_cost_usd !== budget.reserved_cost_usd ||
    attempts.some((attempt) => attempt.cost.reserved_cost_usd !== totalCost.reserved_cost_usd) ||
    !decimalEqualsSum(totalCost.estimated_cost_usd, attempts.map((attempt) => attempt.cost.estimated_cost_usd))
  ) throw new TypeError("total cost does not reconcile to attempts");
  const billedAttempts = attempts.map((attempt) => attempt.cost.billed_cost_usd);
  if (
    attempts.length === 0
      ? totalCost.billed_cost_usd !== null
      : billedAttempts.every((cost): cost is string => cost !== null)
        ? totalCost.billed_cost_usd === null || !decimalEqualsSum(totalCost.billed_cost_usd, billedAttempts)
        : totalCost.billed_cost_usd !== null
  ) throw new TypeError("total cost does not reconcile to billed attempts");
  if (
    budget.status === "reconciled" &&
    budget.reconciled_cost_usd !== totalCost.billed_cost_usd
  ) throw new TypeError("budget cost does not reconcile");

  let notExecuted: NotExecutedDetail | null = null;
  if (execution.not_executed !== null) {
    const detail = record(execution.not_executed, "not_executed");
    exactKeys(detail, NOT_EXECUTED_KEYS, "not_executed");
    ["reason_code", "reason", "gate_policy_version"].forEach((key) => string(detail[key], `not_executed.${key}`));
    strings(detail.failed_gate_checks, "not_executed.failed_gate_checks", false);
    notExecuted = detail as NotExecutedDetail;
  }
  let failure: FailureDetail | null = null;
  if (execution.failure !== null) {
    const detail = record(execution.failure, "failure");
    exactKeys(detail, FAILURE_KEYS, "failure");
    oneOf(detail.category, ["execution_failure", "timeout", "schema_validation", "citation_validation", "contract_violation", "unsupported_output"], "failure.category");
    integer(detail.attempt_count, "failure.attempt_count", 2);
    strings(detail.validation_errors, "failure.validation_errors");
    string(detail.final_reason, "failure.final_reason");
    string(detail.retry_policy_version, "failure.retry_policy_version");
    failure = detail as FailureDetail;
  }
  const opinion = execution.opinion === null ? null : parseOpinion(execution.opinion, context);

  if (execution.execution_state === "not_executed") {
    if (gate.status !== "blocked" || attempts.length !== 0 || opinion !== null || failure !== null || notExecuted === null || budget.reservation_id !== null || budget.status !== "not_reserved") throw new TypeError("invalid not_executed state");
    const failedChecks = gate.checks.filter((check) => !check.passed).map((check) => check.check_id).sort();
    const reportedChecks = [...notExecuted.failed_gate_checks].sort();
    if (
      notExecuted.gate_policy_version !== gate.policy_version ||
      failedChecks.length !== reportedChecks.length ||
      failedChecks.some((check, index) => check !== reportedChecks[index])
    ) throw new TypeError("invalid failed gate checks");
  } else if (execution.execution_state === "failed") {
    if (gate.status !== "passed" || attempts.length === 0 || opinion !== null || failure === null || notExecuted !== null || failure.attempt_count !== attempts.length || failure.retry_policy_version !== execution.retry_policy_version) throw new TypeError("invalid failed state");
  } else {
    const expectedAttemptResult = execution.execution_state === "accepted" ? "accepted" : "abstained";
    if (opinion === null || gate.status !== "passed" || attempts.length === 0 || attempts.at(-1)?.result !== expectedAttemptResult || opinion.execution_state !== execution.execution_state || opinion.execution_id !== execution.id || opinion.grader_id !== execution.grader_id || opinion.grader_version !== execution.grader_version || failure !== null || notExecuted !== null || budget.status !== "reconciled") throw new TypeError(`invalid ${execution.execution_state} state`);
  }
  return execution as GraderExecution;
}
