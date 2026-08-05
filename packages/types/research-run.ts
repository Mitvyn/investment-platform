export const RESEARCH_CONTRACTS = Object.freeze({
  "biotech_moonshot_catalyst_assessment::biotech-moonshot-catalyst-v1": {
    question_type: "biotech_moonshot_catalyst_assessment",
    question_type_version: "biotech_moonshot_catalyst_assessment.v1",
    workflow_config_version: "biotech-moonshot-catalyst-v1",
    thesis_contract_id: "biotech_moonshot_catalyst_assessment",
  },
  "biotech_moonshot_catalyst_personal_research_assessment::biotech-moonshot-catalyst-personal-research-v1": {
    question_type:
      "biotech_moonshot_catalyst_personal_research_assessment",
    question_type_version:
      "biotech_moonshot_catalyst_personal_research_assessment.v1",
    workflow_config_version:
      "biotech-moonshot-catalyst-personal-research-v1",
    thesis_contract_id:
      "biotech_moonshot_catalyst_personal_research_v1",
  },
} as const);

type ResearchContract = (typeof RESEARCH_CONTRACTS)[keyof typeof RESEARCH_CONTRACTS];
export type ResearchQuestionType = ResearchContract["question_type"];
export type ResearchQuestionTypeVersion = ResearchContract["question_type_version"];
export type ResearchWorkflowConfigVersion = ResearchContract["workflow_config_version"];
export type ThesisContractId = ResearchContract["thesis_contract_id"];

export type ResearchQuestionRequest = {
  question_type: ResearchQuestionType;
  security_id: string;
  as_of_cutoff: string;
  workflow_config_version: ResearchWorkflowConfigVersion;
  operator_focus?: string | null;
};

export type NormalizedResearchQuestionRequest = {
  question_type: ResearchQuestionType;
  question_type_version: ResearchQuestionTypeVersion;
  security_id: string;
  as_of_cutoff: string;
  workflow_config_version: ResearchWorkflowConfigVersion;
  thesis_contract_id: ThesisContractId;
  operator_focus_original: string | null;
  operator_focus_normalized: string | null;
};

export type SecurityIdentity = {
  id: string;
  cik: string;
  issuer_name: string;
  symbol: string;
  primary_listing_exchange: string;
};

export type EligibilityCheck = {
  rule_id: string;
  rule_version: string;
  passed: boolean;
  evidence_reference: string | null;
  reason_code: string;
  explanation: string;
  evaluated_at: string;
};

export type EligibilityResult = {
  policy_version: string;
  eligible: boolean;
  checks: EligibilityCheck[];
  evaluated_at: string;
};

export type ResearchRun = {
  contract_version: "research_run.v1";
  id: string;
  operator_id: string;
  security_id: string;
  security_identity: SecurityIdentity;
  question_type: ResearchQuestionType;
  question_type_version: ResearchQuestionTypeVersion;
  workflow_config_version: ResearchWorkflowConfigVersion;
  thesis_contract_id: ThesisContractId;
  as_of_cutoff: string;
  operator_focus_original: string | null;
  operator_focus_normalized: string | null;
  status: "eligibility_evaluated";
  idempotency_key: string;
  eligibility: EligibilityResult;
  created_at: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertRecord(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) throw new TypeError(`invalid ${label}`);
  return value;
}

function assertExactKeys(
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

function assertString(value: unknown, label: string) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`invalid ${label}`);
  }
}

function assertUuid(value: unknown, label: string) {
  assertString(value, label);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value as string)) {
    throw new TypeError(`invalid ${label}`);
  }
}

function assertTimestamp(value: unknown, label: string) {
  assertString(value, label);
  if (
    !/(?:z|[+-]\d{2}:\d{2})$/i.test(value as string) ||
    Number.isNaN(Date.parse(value as string))
  ) {
    throw new TypeError(`invalid ${label}`);
  }
}

function canonicalUtcTimestamp(value: string): string {
  return new Date(value)
    .toISOString()
    .replace(/\.000Z$/, "+00:00")
    .replace(/Z$/, "+00:00");
}

const RESEARCH_RUN_KEYS = [
  "contract_version",
  "id",
  "operator_id",
  "security_id",
  "security_identity",
  "question_type",
  "question_type_version",
  "workflow_config_version",
  "thesis_contract_id",
  "as_of_cutoff",
  "operator_focus_original",
  "operator_focus_normalized",
  "status",
  "idempotency_key",
  "eligibility",
  "created_at",
] as const;

const SECURITY_IDENTITY_KEYS = [
  "id",
  "cik",
  "issuer_name",
  "symbol",
  "primary_listing_exchange",
] as const;

const ELIGIBILITY_KEYS = [
  "policy_version",
  "eligible",
  "checks",
  "evaluated_at",
] as const;

const CHECK_KEYS = [
  "rule_id",
  "rule_version",
  "passed",
  "evidence_reference",
  "reason_code",
  "explanation",
  "evaluated_at",
] as const;

const ELIGIBILITY_RULE_IDS = [
  "security_identity_verified",
  "us_listing",
  "cik_match",
  "common_equity",
  "operating_company",
  "therapeutics_classification",
  "active_therapeutic_program",
  "defined_clinical_or_regulatory_catalyst",
  "required_primary_source_coverage",
] as const;

const REQUEST_REQUIRED_KEYS = [
  "question_type",
  "security_id",
  "as_of_cutoff",
  "workflow_config_version",
] as const;

function resolveResearchContract(
  questionType: unknown,
  workflowConfigVersion: unknown,
): ResearchContract | null {
  if (typeof questionType !== "string" || typeof workflowConfigVersion !== "string") {
    return null;
  }
  const key = `${questionType}::${workflowConfigVersion}` as keyof typeof RESEARCH_CONTRACTS;
  return RESEARCH_CONTRACTS[key] ?? null;
}

export function parseResearchQuestionRequest(
  value: unknown,
): ResearchQuestionRequest {
  const request = assertRecord(value, "research question request");
  const allowed = new Set([...REQUEST_REQUIRED_KEYS, "operator_focus"]);
  if (
    REQUEST_REQUIRED_KEYS.some((key) => !(key in request)) ||
    Object.keys(request).some((key) => !allowed.has(key))
  ) {
    throw new TypeError("invalid research question request fields");
  }
  const contract = resolveResearchContract(
    request.question_type,
    request.workflow_config_version,
  );
  if (contract === null) {
    throw new TypeError("unsupported research question contract");
  }
  assertUuid(request.security_id, "request security id");
  assertTimestamp(request.as_of_cutoff, "request cutoff");
  if (
    request.operator_focus !== undefined &&
    request.operator_focus !== null &&
    typeof request.operator_focus !== "string"
  ) {
    throw new TypeError("invalid operator focus");
  }
  return {
    question_type: contract.question_type,
    security_id: String(request.security_id).toLowerCase(),
    as_of_cutoff: canonicalUtcTimestamp(String(request.as_of_cutoff)),
    workflow_config_version: contract.workflow_config_version,
    operator_focus:
      request.operator_focus === undefined ? null : request.operator_focus,
  } as ResearchQuestionRequest;
}

function normalizeOperatorFocus(value: string | null | undefined): string | null {
  if (value == null) return null;
  if (value.length > 2_000) {
    throw new TypeError("operator focus exceeds 2000 characters");
  }
  const normalized = value.replace(/\s+/g, " ").trim();
  const controlledChanges = [
    /\b(?:add|remove|skip|disable|replace)\b.{0,40}\bgraders?\b/i,
    /\b(?:override|bypass|weaken|change|ignore)\b.{0,40}\b(?:readiness|gate|eligibility|rubric|schema|workflow|disposition|evidence requirements?)\b/i,
  ];
  if (controlledChanges.some((pattern) => pattern.test(normalized))) {
    throw new TypeError("operator focus cannot alter workflow behavior");
  }
  return normalized || null;
}

export function normalizeResearchQuestionRequest(
  request: ResearchQuestionRequest,
): NormalizedResearchQuestionRequest {
  const contract = resolveResearchContract(
    request.question_type,
    request.workflow_config_version,
  );
  if (contract === null) {
    throw new TypeError("unsupported research question contract");
  }
  return {
    question_type: contract.question_type,
    question_type_version: contract.question_type_version,
    security_id: request.security_id.toLowerCase(),
    as_of_cutoff: canonicalUtcTimestamp(request.as_of_cutoff),
    workflow_config_version: contract.workflow_config_version,
    thesis_contract_id: contract.thesis_contract_id,
    operator_focus_original: request.operator_focus ?? null,
    operator_focus_normalized: normalizeOperatorFocus(request.operator_focus),
  };
}

export function mapResearchRunRows(value: unknown): ResearchRun {
  if (!Array.isArray(value) || value.length === 0) {
    throw new TypeError("Research Run view returned no rows");
  }
  const rows = value.map((row) => assertRecord(row, "Research Run view row"));
  rows.sort((left, right) => {
    if (
      typeof left.check_ordinal !== "number" ||
      typeof right.check_ordinal !== "number"
    ) {
      throw new TypeError("invalid Research Run check ordinal");
    }
    return left.check_ordinal - right.check_ordinal;
  });
  const first = rows[0];
  const identityFields = [
    "operator_id",
    "research_run_id",
    "security_id",
    "question_type_version_id",
    "workflow_config_version_id",
    "idempotency_key",
  ] as const;
  for (const row of rows) {
    if (identityFields.some((key) => row[key] !== first[key])) {
      throw new TypeError("inconsistent Research Run view rows");
    }
  }
  const checks = rows.map((row, index) => {
    if (row.check_ordinal !== index + 1) {
      throw new TypeError("non-contiguous Research Run check ordinals");
    }
    return {
      rule_id: row.rule_id,
      rule_version: row.rule_version,
      passed: row.passed,
      evidence_reference: row.evidence_reference,
      reason_code: row.reason_code,
      explanation: row.explanation,
      evaluated_at: row.check_evaluated_at,
    };
  });
  return parseResearchRun({
    contract_version: "research_run.v1",
    id: first.research_run_id,
    operator_id: first.operator_id,
    security_id: first.security_id,
    security_identity: first.security_identity_snapshot,
    question_type: first.question_type,
    question_type_version: first.question_type_version_id,
    workflow_config_version: first.workflow_config_version_id,
    thesis_contract_id: first.thesis_contract_id,
    as_of_cutoff: first.as_of_cutoff,
    operator_focus_original: first.operator_focus_original,
    operator_focus_normalized: first.operator_focus_normalized,
    status: first.status,
    idempotency_key: first.idempotency_key,
    eligibility: {
      policy_version: first.eligibility_policy_version,
      eligible: first.eligible,
      checks,
      evaluated_at: first.evaluated_at,
    },
    created_at: first.created_at,
  });
}

export function parseResearchRun(value: unknown): ResearchRun {
  const run = assertRecord(value, "Research Run");
  assertExactKeys(run, RESEARCH_RUN_KEYS, "Research Run");
  if (run.contract_version !== "research_run.v1") {
    throw new TypeError("invalid Research Run contract version");
  }
  const contract = resolveResearchContract(
    run.question_type,
    run.workflow_config_version,
  );
  if (
    contract === null ||
    run.question_type_version !== contract.question_type_version ||
    run.thesis_contract_id !== contract.thesis_contract_id ||
    run.status !== "eligibility_evaluated"
  ) {
    throw new TypeError("incompatible Research Run versions or state");
  }
  assertUuid(run.id, "run id");
  assertUuid(run.operator_id, "operator id");
  assertUuid(run.security_id, "security id");
  assertTimestamp(run.as_of_cutoff, "cutoff");
  assertTimestamp(run.created_at, "created timestamp");
  if (
    !/^[0-9a-f]{64}$/.test(run.idempotency_key as string) ||
    (run.operator_focus_original !== null &&
      typeof run.operator_focus_original !== "string") ||
    (run.operator_focus_normalized !== null &&
      typeof run.operator_focus_normalized !== "string")
  ) {
    throw new TypeError("invalid Research Run identity or focus");
  }

  const security = assertRecord(run.security_identity, "security identity");
  assertExactKeys(security, SECURITY_IDENTITY_KEYS, "security identity");
  assertUuid(security.id, "security identity id");
  if (security.id !== run.security_id) {
    throw new TypeError("inconsistent Research Run security identity");
  }
  for (const key of ["cik", "issuer_name", "symbol", "primary_listing_exchange"] as const) {
    if (typeof security[key] !== "string") {
      throw new TypeError(`invalid security identity ${key}`);
    }
  }

  const eligibility = assertRecord(run.eligibility, "eligibility result");
  assertExactKeys(eligibility, ELIGIBILITY_KEYS, "eligibility result");
  if (
    eligibility.policy_version !== "biotech-security-eligibility-v1" ||
    typeof eligibility.eligible !== "boolean" ||
    !Array.isArray(eligibility.checks)
  ) {
    throw new TypeError("invalid Research Run eligibility result");
  }
  assertTimestamp(eligibility.evaluated_at, "eligibility evaluation timestamp");
  if (eligibility.checks.length !== ELIGIBILITY_RULE_IDS.length) {
    throw new TypeError("invalid Research Run eligibility rule count");
  }
  for (const [index, rawCheck] of eligibility.checks.entries()) {
    const check = assertRecord(rawCheck, "eligibility check");
    assertExactKeys(check, CHECK_KEYS, "eligibility check");
    const expectedRuleId = ELIGIBILITY_RULE_IDS[index];
    if (
      check.rule_id !== expectedRuleId ||
      check.rule_version !== `${expectedRuleId}.v1`
    ) {
      throw new TypeError("invalid Research Run eligibility rule sequence");
    }
    assertString(check.reason_code, "eligibility reason code");
    assertString(check.explanation, "eligibility explanation");
    assertTimestamp(check.evaluated_at, "eligibility check timestamp");
    if (
      typeof check.passed !== "boolean" ||
      (check.evidence_reference !== null &&
        typeof check.evidence_reference !== "string")
    ) {
      throw new TypeError("invalid eligibility check result");
    }
  }
  if (
    eligibility.eligible !==
    eligibility.checks.every(
      (check) => assertRecord(check, "eligibility check").passed === true,
    )
  ) {
    throw new TypeError("inconsistent Research Run eligibility outcome");
  }
  if (
    eligibility.checks[0].passed === true &&
    (!/^\d{10}$/.test(security.cik as string) ||
      !String(security.issuer_name).trim() ||
      !/^[A-Z][A-Z0-9.-]{0,9}$/.test(security.symbol as string) ||
      !String(security.primary_listing_exchange).trim())
  ) {
    throw new TypeError("inconsistent verified security identity");
  }
  return run as ResearchRun;
}
