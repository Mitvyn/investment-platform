import type { ResearchDisposition } from "./committee-memo.ts";
import type { CommitteeStatus } from "./committee.ts";
import type {
  ResearchQuestionTypeVersion,
  ThesisContractId,
} from "./research-run.ts";

const THESIS_CONTRACTS = Object.freeze({
  biotech_moonshot_catalyst_assessment: {
    questionTypeVersion: "biotech_moonshot_catalyst_assessment.v1",
    workflowConfigVersion: "biotech-moonshot-catalyst-v1",
    gatePolicyVersion: "biotech-readiness.v1",
  },
  biotech_moonshot_catalyst_personal_research_v1: {
    questionTypeVersion:
      "biotech_moonshot_catalyst_personal_research_assessment.v1",
    workflowConfigVersion:
      "biotech-moonshot-catalyst-personal-research-v1",
    gatePolicyVersion: "biotech-personal-readiness.v1",
  },
} as const satisfies Record<
  ThesisContractId,
  {
    questionTypeVersion: ResearchQuestionTypeVersion;
    workflowConfigVersion: string;
    gatePolicyVersion: string;
  }
>);

function thesisContract(value: unknown) {
  if (typeof value !== "string" || !(value in THESIS_CONTRACTS)) {
    throw new TypeError("invalid thesis contract identity");
  }
  return THESIS_CONTRACTS[value as ThesisContractId];
}

export const READINESS_CHECK_IDS = Object.freeze([
  "committee_status_complete",
  "all_eligible_graders_accepted",
  "zero_eligible_abstentions",
  "zero_required_grader_failures",
  "blocking_evidence_requirements_satisfied",
  "aligned_valuation_snapshot_required",
  "source_freshness_passed",
  "material_claims_citation_valid",
  "grader_decision_questions_answered",
  "material_disagreement_preserved",
  "thesis_required_contents_present",
] as const);

export type ReadinessCheckId = (typeof READINESS_CHECK_IDS)[number];
export type ReadinessStatus = "passed" | "blocked" | "not_requested";

export type ReadinessCheck = {
  check_id: ReadinessCheckId;
  check_version: string;
  reason_code: string;
  explanation: string;
  reference_ids: string[];
};

export type ReadinessBlockingReason = {
  reason_code: string;
  check_id: ReadinessCheckId;
  explanation: string;
};

export type RequiredNextEvidence = {
  requirement_id: string;
  description: string;
  affected_check_ids: ReadinessCheckId[];
};

export type ReadinessGateResult = {
  contract_version: "readiness_gate_result.v1";
  readiness_gate_result_id: string;
  operator_id: string;
  security_id: string;
  thesis_contract_id: ThesisContractId;
  research_run_id: string;
  evidence_bundle_id: string;
  evidence_bundle_hash: string;
  validated_grader_opinion_ids: string[];
  committee_result_id: string;
  committee_memo_id: string;
  committee_status: CommitteeStatus;
  requested_disposition: ResearchDisposition;
  final_disposition: ResearchDisposition;
  readiness_status: ReadinessStatus;
  gate_policy_version: string;
  passed_checks: ReadinessCheck[];
  failed_checks: ReadinessCheck[];
  blocking_reasons: ReadinessBlockingReason[];
  required_next_evidence: RequiredNextEvidence[];
  evaluated_at: string;
};

export type ReadinessValidationContext = {
  operatorId: string;
  securityId: string;
  thesisContractId: string;
  researchRunId: string;
  evidenceBundleId: string;
  evidenceBundleHash: string;
  validatedGraderOpinionIds: readonly string[];
  committeeResultId: string;
  committeeMemoId: string;
  committeeStatus: CommitteeStatus;
  requestedDisposition: ResearchDisposition;
  allowedReferenceIds?: readonly string[];
};

export type ThesisStatus = "canonical" | "provisional";

export type ThesisContent = {
  core_thesis_statement_ids: string[];
  unresolved_disagreement_ids: string[];
  invalidation_statement_ids: string[];
  evidence_gap_statement_ids: string[];
  review_trigger_statement_id: string;
};

export type ThesisVersion = {
  contract_version: "thesis_version.v1";
  thesis_version_id: string;
  thesis_status: ThesisStatus;
  operator_id: string;
  security_id: string;
  thesis_contract_id: ThesisContractId;
  previous_canonical_thesis_version_id: string | null;
  based_on_thesis_version_id: string | null;
  research_run_id: string;
  evidence_bundle_id: string;
  evidence_bundle_hash: string;
  question_type_version: ResearchQuestionTypeVersion;
  workflow_config_version: string;
  proposition_id: string;
  proposition_version: string;
  validated_grader_opinion_ids: string[];
  committee_result_id: string;
  committee_memo_id: string;
  committee_status: "complete" | "complete_with_abstentions";
  readiness_gate_result_id: string;
  readiness_gate_policy_version: string;
  requested_disposition: ResearchDisposition;
  final_disposition: ResearchDisposition;
  content: ThesisContent;
  created_at: string;
};

export type ThesisValidationContext = {
  readinessResult: ReadinessGateResult;
  questionTypeVersion: string;
  workflowConfigVersion: string;
  propositionId: string;
  propositionVersion: string;
  memoStatementIds: readonly string[];
  memoDisagreementIds: readonly string[];
  expectedPreviousCanonicalThesisVersionId?: string | null;
  expectedBasedOnThesisVersionId?: string | null;
};

export type ThesisCreationOutcome =
  | "canonical_created"
  | "provisional_created"
  | "no_thesis";

export type ThesisCreationResult = {
  contract_version: "thesis_creation_result.v1";
  thesis_creation_result_id: string;
  operator_id: string;
  security_id: string;
  thesis_contract_id: ThesisContractId;
  research_run_id: string;
  committee_result_id: string;
  readiness_gate_result_id: string;
  committee_status: CommitteeStatus;
  creation_outcome: ThesisCreationOutcome;
  thesis_version_id: string | null;
  reason_code: string;
  created_at: string;
};

export type ThesisCreationValidationContext = {
  readinessResult: ReadinessGateResult;
  thesisVersion: ThesisVersion | null;
};

export type ThesisChain = {
  contract_version: "thesis_chain.v1";
  operator_id: string;
  security_id: string;
  thesis_contract_id: ThesisContractId;
  active_canonical_thesis_version_id: string | null;
  canonical_versions: ThesisVersion[];
  provisional_branches: ThesisVersion[];
  generated_at: string;
};

export type ThesisChainValidationContext = {
  operatorId: string;
  securityId: string;
  thesisContractId: string;
};

const READINESS_KEYS = [
  "contract_version",
  "readiness_gate_result_id",
  "operator_id",
  "security_id",
  "thesis_contract_id",
  "research_run_id",
  "evidence_bundle_id",
  "evidence_bundle_hash",
  "validated_grader_opinion_ids",
  "committee_result_id",
  "committee_memo_id",
  "committee_status",
  "requested_disposition",
  "final_disposition",
  "readiness_status",
  "gate_policy_version",
  "passed_checks",
  "failed_checks",
  "blocking_reasons",
  "required_next_evidence",
  "evaluated_at",
] as const;

const CHECK_KEYS = [
  "check_id",
  "check_version",
  "reason_code",
  "explanation",
  "reference_ids",
] as const;

const BLOCKING_REASON_KEYS = ["reason_code", "check_id", "explanation"] as const;
const NEXT_EVIDENCE_KEYS = [
  "requirement_id",
  "description",
  "affected_check_ids",
] as const;
const THESIS_KEYS = [
  "contract_version",
  "thesis_version_id",
  "thesis_status",
  "operator_id",
  "security_id",
  "thesis_contract_id",
  "previous_canonical_thesis_version_id",
  "based_on_thesis_version_id",
  "research_run_id",
  "evidence_bundle_id",
  "evidence_bundle_hash",
  "question_type_version",
  "workflow_config_version",
  "proposition_id",
  "proposition_version",
  "validated_grader_opinion_ids",
  "committee_result_id",
  "committee_memo_id",
  "committee_status",
  "readiness_gate_result_id",
  "readiness_gate_policy_version",
  "requested_disposition",
  "final_disposition",
  "content",
  "created_at",
] as const;
const THESIS_CONTENT_KEYS = [
  "core_thesis_statement_ids",
  "unresolved_disagreement_ids",
  "invalidation_statement_ids",
  "evidence_gap_statement_ids",
  "review_trigger_statement_id",
] as const;
const CREATION_KEYS = [
  "contract_version",
  "thesis_creation_result_id",
  "operator_id",
  "security_id",
  "thesis_contract_id",
  "research_run_id",
  "committee_result_id",
  "readiness_gate_result_id",
  "committee_status",
  "creation_outcome",
  "thesis_version_id",
  "reason_code",
  "created_at",
] as const;
const CHAIN_KEYS = [
  "contract_version",
  "operator_id",
  "security_id",
  "thesis_contract_id",
  "active_canonical_thesis_version_id",
  "canonical_versions",
  "provisional_branches",
  "generated_at",
] as const;
const DISPOSITIONS = ["reject", "monitor", "deep_research", "decision_ready"] as const;
const COMMITTEE_STATUSES = [
  "complete",
  "complete_with_abstentions",
  "incomplete_required_grader_failed",
  "insufficient_accepted_opinions",
] as const;

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError(`invalid ${label}`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
  label: string,
) {
  const actual = Object.keys(value).sort();
  const keys = [...expected].sort();
  if (
    actual.length !== keys.length ||
    actual.some((key, index) => key !== keys[index])
  ) {
    throw new TypeError(`invalid ${label} fields`);
  }
}

function nonEmptyString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`invalid ${label}`);
  }
  return value;
}

function uuid(value: unknown, label: string): string {
  const candidate = nonEmptyString(value, label);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(candidate)) {
    throw new TypeError(`invalid ${label}`);
  }
  return candidate;
}

function timestamp(value: unknown, label: string): string {
  const candidate = nonEmptyString(value, label);
  if (!/(?:z|[+-]\d{2}:\d{2})$/i.test(candidate) || Number.isNaN(Date.parse(candidate))) {
    throw new TypeError(`invalid ${label}`);
  }
  return candidate;
}

function stringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value)) throw new TypeError(`invalid ${label}`);
  const result = value.map((item) => nonEmptyString(item, label));
  if (new Set(result).size !== result.length) throw new TypeError(`invalid ${label}`);
  return result;
}

function sameStrings(left: readonly string[], right: readonly string[]) {
  return (
    new Set(left).size === left.length &&
    new Set(right).size === right.length &&
    [...left].sort().join("\u0000") === [...right].sort().join("\u0000")
  );
}

function parseCheck(value: unknown, label: string): ReadinessCheck {
  const check = record(value, label);
  exactKeys(check, CHECK_KEYS, label);
  if (!READINESS_CHECK_IDS.includes(check.check_id as ReadinessCheckId)) {
    throw new TypeError(`invalid ${label}.check_id`);
  }
  nonEmptyString(check.check_version, `${label}.check_version`);
  nonEmptyString(check.reason_code, `${label}.reason_code`);
  nonEmptyString(check.explanation, `${label}.explanation`);
  stringArray(check.reference_ids, `${label}.reference_ids`);
  return check as ReadinessCheck;
}

export function parseReadinessGateResult(
  value: unknown,
  context: ReadinessValidationContext,
): ReadinessGateResult {
  const result = record(value, "readiness gate result");
  exactKeys(result, READINESS_KEYS, "readiness gate result");
  if (result.contract_version !== "readiness_gate_result.v1") {
    throw new TypeError("invalid readiness contract version");
  }
  uuid(result.readiness_gate_result_id, "readiness gate result id");
  for (const [key, expected] of [
    ["operator_id", context.operatorId],
    ["security_id", context.securityId],
    ["thesis_contract_id", context.thesisContractId],
    ["research_run_id", context.researchRunId],
    ["evidence_bundle_id", context.evidenceBundleId],
    ["evidence_bundle_hash", context.evidenceBundleHash],
    ["committee_result_id", context.committeeResultId],
    ["committee_memo_id", context.committeeMemoId],
    ["committee_status", context.committeeStatus],
    ["requested_disposition", context.requestedDisposition],
  ] as const) {
    if (result[key] !== expected) throw new TypeError("readiness identity mismatch");
  }
  uuid(result.operator_id, "operator id");
  uuid(result.security_id, "security id");
  uuid(result.research_run_id, "research run id");
  uuid(result.evidence_bundle_id, "evidence bundle id");
  uuid(result.committee_result_id, "committee result id");
  uuid(result.committee_memo_id, "committee memo id");
  const contract = thesisContract(result.thesis_contract_id);
  if (
    typeof result.evidence_bundle_hash !== "string" ||
    !/^[0-9a-f]{64}$/.test(result.evidence_bundle_hash) ||
    !COMMITTEE_STATUSES.includes(result.committee_status as CommitteeStatus) ||
    !DISPOSITIONS.includes(result.requested_disposition as ResearchDisposition) ||
    !DISPOSITIONS.includes(result.final_disposition as ResearchDisposition) ||
    !["passed", "blocked", "not_requested"].includes(result.readiness_status as string)
  ) {
    throw new TypeError("invalid readiness state");
  }
  if (result.gate_policy_version !== contract.gatePolicyVersion) {
    throw new TypeError("readiness gate policy identity mismatch");
  }
  timestamp(result.evaluated_at, "readiness evaluated_at");
  const opinions = stringArray(
    result.validated_grader_opinion_ids,
    "validated grader opinion ids",
  );
  opinions.forEach((id) => uuid(id, "validated grader opinion id"));
  if (!sameStrings(opinions, context.validatedGraderOpinionIds)) {
    throw new TypeError("readiness opinion identity mismatch");
  }
  if (!Array.isArray(result.passed_checks) || !Array.isArray(result.failed_checks)) {
    throw new TypeError("invalid readiness checks");
  }
  const passed = result.passed_checks.map((item, index) =>
    parseCheck(item, `passed_checks[${index}]`),
  );
  const failed = result.failed_checks.map((item, index) =>
    parseCheck(item, `failed_checks[${index}]`),
  );
  const allCheckIds = [...passed, ...failed].map((check) => check.check_id);
  if (!sameStrings(allCheckIds, READINESS_CHECK_IDS)) {
    throw new TypeError("readiness check set mismatch");
  }
  const allowedReferences = new Set([
    context.researchRunId,
    context.evidenceBundleId,
    context.committeeResultId,
    context.committeeMemoId,
    ...context.validatedGraderOpinionIds,
    ...(context.allowedReferenceIds ?? []),
  ]);
  for (const check of [...passed, ...failed]) {
    if (check.reference_ids.some((id) => !allowedReferences.has(id))) {
      throw new TypeError("unresolved readiness reference");
    }
  }
  if (!Array.isArray(result.blocking_reasons)) {
    throw new TypeError("invalid blocking reasons");
  }
  const blockingReasons = result.blocking_reasons.map((item, index) => {
    const reason = record(item, `blocking_reasons[${index}]`);
    exactKeys(reason, BLOCKING_REASON_KEYS, "blocking reason");
    nonEmptyString(reason.reason_code, "blocking reason code");
    nonEmptyString(reason.explanation, "blocking explanation");
    if (!failed.some((check) => check.check_id === reason.check_id)) {
      throw new TypeError("blocking reason does not resolve to failed check");
    }
    return reason;
  });
  if (new Set(blockingReasons.map((reason) => reason.reason_code)).size !== blockingReasons.length) {
    throw new TypeError("invalid blocking reasons");
  }
  if (!Array.isArray(result.required_next_evidence)) {
    throw new TypeError("invalid required next evidence");
  }
  const nextEvidence = result.required_next_evidence.map((item, index) => {
    const requirement = record(item, `required_next_evidence[${index}]`);
    exactKeys(requirement, NEXT_EVIDENCE_KEYS, "required next evidence");
    nonEmptyString(requirement.requirement_id, "next evidence requirement id");
    nonEmptyString(requirement.description, "next evidence description");
    const affected = stringArray(
      requirement.affected_check_ids,
      "next evidence affected check ids",
    );
    if (
      affected.length === 0 ||
      affected.some((id) => !failed.some((check) => check.check_id === id))
    ) {
      throw new TypeError("next evidence does not resolve to failed check");
    }
    return requirement;
  });
  if (new Set(nextEvidence.map((item) => item.requirement_id)).size !== nextEvidence.length) {
    throw new TypeError("invalid required next evidence");
  }
  const requested = result.requested_disposition as ResearchDisposition;
  const final = result.final_disposition as ResearchDisposition;
  const allowedPair = requested === final || (
    requested === "decision_ready" && final === "deep_research"
  );
  if (!allowedPair) throw new TypeError("readiness gate cannot upgrade disposition");
  if (requested !== "decision_ready") {
    if (result.readiness_status !== "not_requested" || final !== requested) {
      throw new TypeError("invalid non-requested readiness result");
    }
  } else if (final === "decision_ready") {
    if (
      result.readiness_status !== "passed" ||
      failed.length !== 0 ||
      blockingReasons.length !== 0 ||
      nextEvidence.length !== 0
    ) {
      throw new TypeError("decision_ready requires every readiness check");
    }
  } else if (
    result.readiness_status !== "blocked" ||
    failed.length === 0 ||
    blockingReasons.length === 0 ||
    nextEvidence.length === 0
  ) {
    throw new TypeError("invalid readiness downgrade");
  }
  return value as ReadinessGateResult;
}

export function parseThesisVersion(
  value: unknown,
  context: ThesisValidationContext,
): ThesisVersion {
  const thesis = record(value, "thesis version");
  exactKeys(thesis, THESIS_KEYS, "thesis version");
  if (thesis.contract_version !== "thesis_version.v1") {
    throw new TypeError("invalid thesis contract version");
  }
  uuid(thesis.thesis_version_id, "thesis version id");
  const readiness = context.readinessResult;
  for (const [key, expected] of [
    ["operator_id", readiness.operator_id],
    ["security_id", readiness.security_id],
    ["thesis_contract_id", readiness.thesis_contract_id],
    ["research_run_id", readiness.research_run_id],
    ["evidence_bundle_id", readiness.evidence_bundle_id],
    ["evidence_bundle_hash", readiness.evidence_bundle_hash],
    ["question_type_version", context.questionTypeVersion],
    ["workflow_config_version", context.workflowConfigVersion],
    ["proposition_id", context.propositionId],
    ["proposition_version", context.propositionVersion],
    ["committee_result_id", readiness.committee_result_id],
    ["committee_memo_id", readiness.committee_memo_id],
    ["committee_status", readiness.committee_status],
    ["readiness_gate_result_id", readiness.readiness_gate_result_id],
    ["readiness_gate_policy_version", readiness.gate_policy_version],
    ["requested_disposition", readiness.requested_disposition],
    ["final_disposition", readiness.final_disposition],
  ] as const) {
    if (thesis[key] !== expected) throw new TypeError("thesis provenance mismatch");
  }
  for (const key of [
    "operator_id",
    "security_id",
    "research_run_id",
    "evidence_bundle_id",
    "committee_result_id",
    "committee_memo_id",
    "readiness_gate_result_id",
  ] as const) {
    uuid(thesis[key], `thesis ${key}`);
  }
  const contract = thesisContract(thesis.thesis_contract_id);
  if (
    thesis.question_type_version !== contract.questionTypeVersion ||
    thesis.workflow_config_version !== contract.workflowConfigVersion ||
    thesis.readiness_gate_policy_version !== contract.gatePolicyVersion ||
    typeof thesis.evidence_bundle_hash !== "string" ||
    !/^[0-9a-f]{64}$/.test(thesis.evidence_bundle_hash) ||
    !["canonical", "provisional"].includes(thesis.thesis_status as string)
  ) {
    throw new TypeError("invalid thesis identity or status");
  }
  for (const key of [
    "workflow_config_version",
    "proposition_id",
    "proposition_version",
    "readiness_gate_policy_version",
  ] as const) {
    nonEmptyString(thesis[key], `thesis ${key}`);
  }
  timestamp(thesis.created_at, "thesis created_at");
  if (Date.parse(thesis.created_at as string) < Date.parse(readiness.evaluated_at)) {
    throw new TypeError("thesis predates readiness result");
  }
  const opinions = stringArray(
    thesis.validated_grader_opinion_ids,
    "thesis validated grader opinion ids",
  );
  opinions.forEach((id) => uuid(id, "thesis validated grader opinion id"));
  if (!sameStrings(opinions, readiness.validated_grader_opinion_ids)) {
    throw new TypeError("thesis opinion identity mismatch");
  }
  for (const key of [
    "previous_canonical_thesis_version_id",
    "based_on_thesis_version_id",
  ] as const) {
    if (thesis[key] !== null) uuid(thesis[key], key);
  }
  const expectedPrevious = context.expectedPreviousCanonicalThesisVersionId ?? null;
  const expectedBasis = context.expectedBasedOnThesisVersionId ?? expectedPrevious;
  if (
    thesis.previous_canonical_thesis_version_id !== expectedPrevious ||
    thesis.based_on_thesis_version_id !== expectedBasis
  ) {
    throw new TypeError("thesis chain reference mismatch");
  }
  const content = record(thesis.content, "thesis content");
  exactKeys(content, THESIS_CONTENT_KEYS, "thesis content");
  const core = stringArray(content.core_thesis_statement_ids, "core thesis statements");
  const unresolved = stringArray(
    content.unresolved_disagreement_ids,
    "unresolved thesis disagreements",
  );
  const invalidation = stringArray(
    content.invalidation_statement_ids,
    "thesis invalidation statements",
  );
  const gaps = stringArray(content.evidence_gap_statement_ids, "thesis evidence gaps");
  const reviewTrigger = nonEmptyString(
    content.review_trigger_statement_id,
    "thesis review trigger statement",
  );
  if (core.length === 0 || invalidation.length === 0) {
    throw new TypeError("thesis required contents missing");
  }
  const allowedStatements = new Set(context.memoStatementIds);
  if (
    [...core, ...invalidation, ...gaps, reviewTrigger].some(
      (id) => !allowedStatements.has(id),
    ) ||
    unresolved.some((id) => !context.memoDisagreementIds.includes(id))
  ) {
    throw new TypeError("unresolved thesis memo reference");
  }
  if (thesis.thesis_status === "canonical") {
    if (thesis.committee_status !== "complete") {
      throw new TypeError("canonical thesis requires complete committee");
    }
  } else if (
    thesis.committee_status !== "complete_with_abstentions" ||
    thesis.final_disposition === "decision_ready"
  ) {
    throw new TypeError("provisional thesis requires abstentions and cannot be decision_ready");
  }
  if (
    thesis.final_disposition === "decision_ready" &&
    readiness.readiness_status !== "passed"
  ) {
    throw new TypeError("decision_ready thesis requires passed readiness gate");
  }
  return value as ThesisVersion;
}

export function parseThesisCreationResult(
  value: unknown,
  context: ThesisCreationValidationContext,
): ThesisCreationResult {
  const creation = record(value, "thesis creation result");
  exactKeys(creation, CREATION_KEYS, "thesis creation result");
  if (creation.contract_version !== "thesis_creation_result.v1") {
    throw new TypeError("invalid thesis creation contract version");
  }
  uuid(creation.thesis_creation_result_id, "thesis creation result id");
  const readiness = context.readinessResult;
  for (const [key, expected] of [
    ["operator_id", readiness.operator_id],
    ["security_id", readiness.security_id],
    ["thesis_contract_id", readiness.thesis_contract_id],
    ["research_run_id", readiness.research_run_id],
    ["committee_result_id", readiness.committee_result_id],
    ["readiness_gate_result_id", readiness.readiness_gate_result_id],
    ["committee_status", readiness.committee_status],
  ] as const) {
    if (creation[key] !== expected) {
      throw new TypeError("thesis creation provenance mismatch");
    }
  }
  timestamp(creation.created_at, "thesis creation timestamp");
  nonEmptyString(creation.reason_code, "thesis creation reason code");
  if (Date.parse(creation.created_at as string) < Date.parse(readiness.evaluated_at)) {
    throw new TypeError("thesis creation predates readiness");
  }
  const expectedOutcome = readiness.committee_status === "complete"
    ? "canonical_created"
    : readiness.committee_status === "complete_with_abstentions"
      ? "provisional_created"
      : "no_thesis";
  if (creation.creation_outcome !== expectedOutcome) {
    throw new TypeError("invalid thesis creation outcome");
  }
  if (expectedOutcome === "no_thesis") {
    if (context.thesisVersion !== null || creation.thesis_version_id !== null) {
      throw new TypeError("incomplete committee cannot create thesis");
    }
  } else {
    if (context.thesisVersion === null) {
      throw new TypeError("created thesis outcome requires thesis version");
    }
    uuid(creation.thesis_version_id, "created thesis version id");
    if (
      creation.thesis_version_id !== context.thesisVersion.thesis_version_id ||
      context.thesisVersion.research_run_id !== readiness.research_run_id ||
      context.thesisVersion.thesis_status !== (
        expectedOutcome === "canonical_created" ? "canonical" : "provisional"
      )
    ) {
      throw new TypeError("created thesis identity mismatch");
    }
  }
  return value as ThesisCreationResult;
}

function parsePublicThesisVersion(
  value: unknown,
  ownership: ThesisChainValidationContext,
): ThesisVersion {
  const thesis = record(value, "public thesis version");
  exactKeys(thesis, THESIS_KEYS, "public thesis version");
  if (thesis.contract_version !== "thesis_version.v1") {
    throw new TypeError("invalid public thesis contract version");
  }
  if (
    thesis.operator_id !== ownership.operatorId ||
    thesis.security_id !== ownership.securityId ||
    thesis.thesis_contract_id !== ownership.thesisContractId
  ) {
    throw new TypeError("public thesis ownership mismatch");
  }
  for (const key of [
    "thesis_version_id",
    "operator_id",
    "security_id",
    "research_run_id",
    "evidence_bundle_id",
    "committee_result_id",
    "committee_memo_id",
    "readiness_gate_result_id",
  ] as const) {
    uuid(thesis[key], `public thesis ${key}`);
  }
  const contract = thesisContract(thesis.thesis_contract_id);
  if (
    thesis.question_type_version !== contract.questionTypeVersion ||
    typeof thesis.evidence_bundle_hash !== "string" ||
    !/^[0-9a-f]{64}$/.test(thesis.evidence_bundle_hash) ||
    !DISPOSITIONS.includes(thesis.requested_disposition as ResearchDisposition) ||
    !DISPOSITIONS.includes(thesis.final_disposition as ResearchDisposition)
  ) {
    throw new TypeError("invalid public thesis identity");
  }
  for (const key of [
    "workflow_config_version",
    "proposition_id",
    "proposition_version",
    "readiness_gate_policy_version",
  ] as const) {
    nonEmptyString(thesis[key], `public thesis ${key}`);
  }
  timestamp(thesis.created_at, "public thesis created_at");
  const opinions = stringArray(
    thesis.validated_grader_opinion_ids,
    "public thesis opinion ids",
  );
  opinions.forEach((id) => uuid(id, "public thesis opinion id"));
  for (const key of [
    "previous_canonical_thesis_version_id",
    "based_on_thesis_version_id",
  ] as const) {
    if (thesis[key] !== null) uuid(thesis[key], `public thesis ${key}`);
  }
  const content = record(thesis.content, "public thesis content");
  exactKeys(content, THESIS_CONTENT_KEYS, "public thesis content");
  const core = stringArray(content.core_thesis_statement_ids, "public core thesis");
  stringArray(content.unresolved_disagreement_ids, "public thesis disagreements");
  const invalidation = stringArray(
    content.invalidation_statement_ids,
    "public thesis invalidation",
  );
  stringArray(content.evidence_gap_statement_ids, "public thesis gaps");
  nonEmptyString(content.review_trigger_statement_id, "public thesis review trigger");
  if (core.length === 0 || invalidation.length === 0) {
    throw new TypeError("public thesis required contents missing");
  }
  if (thesis.thesis_status === "canonical") {
    if (thesis.committee_status !== "complete") {
      throw new TypeError("public canonical thesis requires complete committee");
    }
  } else if (thesis.thesis_status === "provisional") {
    if (
      thesis.committee_status !== "complete_with_abstentions" ||
      thesis.final_disposition === "decision_ready"
    ) {
      throw new TypeError("invalid public provisional thesis");
    }
  } else {
    throw new TypeError("invalid public thesis status");
  }
  return value as ThesisVersion;
}

export function parseThesisChain(
  value: unknown,
  context: ThesisChainValidationContext,
): ThesisChain {
  const chain = record(value, "thesis chain");
  exactKeys(chain, CHAIN_KEYS, "thesis chain");
  if (chain.contract_version !== "thesis_chain.v1") {
    throw new TypeError("invalid thesis chain contract version");
  }
  if (
    chain.operator_id !== context.operatorId ||
    chain.security_id !== context.securityId ||
    chain.thesis_contract_id !== context.thesisContractId
  ) {
    throw new TypeError("thesis chain ownership mismatch");
  }
  uuid(chain.operator_id, "thesis chain operator id");
  uuid(chain.security_id, "thesis chain security id");
  thesisContract(chain.thesis_contract_id);
  timestamp(chain.generated_at, "thesis chain generated_at");
  if (!Array.isArray(chain.canonical_versions) || !Array.isArray(chain.provisional_branches)) {
    throw new TypeError("invalid thesis chain versions");
  }
  const canonical = chain.canonical_versions.map((item) =>
    parsePublicThesisVersion(item, context),
  );
  const provisional = chain.provisional_branches.map((item) =>
    parsePublicThesisVersion(item, context),
  );
  if (
    canonical.some((item) => item.thesis_status !== "canonical") ||
    provisional.some((item) => item.thesis_status !== "provisional")
  ) {
    throw new TypeError("thesis chain branch status mismatch");
  }
  const all = [...canonical, ...provisional];
  if (
    new Set(all.map((item) => item.thesis_version_id)).size !== all.length ||
    new Set(all.map((item) => item.research_run_id)).size !== all.length
  ) {
    throw new TypeError("duplicate thesis identity or research run");
  }
  canonical.forEach((item, index) => {
    const previous = index === 0 ? null : canonical[index - 1].thesis_version_id;
    if (
      item.previous_canonical_thesis_version_id !== previous ||
      item.based_on_thesis_version_id !== previous ||
      (index > 0 && Date.parse(item.created_at) <= Date.parse(canonical[index - 1].created_at))
    ) {
      throw new TypeError("invalid canonical thesis chain");
    }
  });
  const canonicalById = new Map(canonical.map((item) => [item.thesis_version_id, item]));
  for (const item of provisional) {
    if (item.previous_canonical_thesis_version_id !== item.based_on_thesis_version_id) {
      throw new TypeError("provisional thesis cannot supersede canonical chain");
    }
    const basis = item.based_on_thesis_version_id;
    if (basis !== null) {
      const canonicalBasis = canonicalById.get(basis);
      if (
        canonicalBasis === undefined ||
        Date.parse(item.created_at) <= Date.parse(canonicalBasis.created_at)
      ) {
        throw new TypeError("invalid provisional thesis basis");
      }
    } else if (
      canonical.length !== 0 &&
      Date.parse(item.created_at) >= Date.parse(canonical[0].created_at)
    ) {
      throw new TypeError("provisional thesis basis missing");
    }
  }
  const activeId = canonical.length === 0
    ? null
    : canonical[canonical.length - 1].thesis_version_id;
  if (chain.active_canonical_thesis_version_id !== activeId) {
    throw new TypeError("active canonical thesis mismatch");
  }
  if (
    all.some((item) => Date.parse(item.created_at) > Date.parse(chain.generated_at as string))
  ) {
    throw new TypeError("thesis chain generated before version");
  }
  return value as ThesisChain;
}
