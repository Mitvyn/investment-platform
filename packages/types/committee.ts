export type CommitteeGraderId =
  | "moonshot"
  | "catalyst"
  | "biotech"
  | "risk_dilution"
  | "valuation";

export type CommitteeGraderDefinition = {
  grader_id: CommitteeGraderId;
  grader_version: string;
  grader_contract_version: string;
  output_schema_version: string;
  owned_decision_question: string;
  required_when_eligible: true;
};

export const MVP_COMMITTEE_ROSTER = Object.freeze([
  {
    grader_id: "moonshot",
    grader_version: "moonshot-grader-v1",
    grader_contract_version: "moonshot-grader-contract-v1",
    output_schema_version: "moonshot_grader_payload.v1",
    owned_decision_question: "Is the opportunity meaningfully asymmetric?",
    required_when_eligible: true,
  },
  {
    grader_id: "catalyst",
    grader_version: "catalyst-grader-v1",
    grader_contract_version: "catalyst-grader-contract-v1",
    output_schema_version: "catalyst_grader_payload.v1",
    owned_decision_question: "What event resolves uncertainty, when, and with what outcomes?",
    required_when_eligible: true,
  },
  {
    grader_id: "biotech",
    grader_version: "biotech-grader-v1",
    grader_contract_version: "biotech-grader-contract-v1",
    output_schema_version: "biotech_grader_payload.v1",
    owned_decision_question: "Is the scientific and clinical evidence credible?",
    required_when_eligible: true,
  },
  {
    grader_id: "risk_dilution",
    grader_version: "risk_dilution-grader-v1",
    grader_contract_version: "risk_dilution-grader-contract-v1",
    output_schema_version: "risk_dilution_grader_payload.v1",
    owned_decision_question: "Can shareholders survive financially until the thesis resolves?",
    required_when_eligible: true,
  },
  {
    grader_id: "valuation",
    grader_version: "valuation-grader-v1",
    grader_contract_version: "valuation-grader-contract-v1",
    output_schema_version: "valuation_grader_payload.v1",
    owned_decision_question: "What outcomes and assumptions justify the current or implied value?",
    required_when_eligible: true,
  },
] as const satisfies readonly CommitteeGraderDefinition[]);

export type CommitteeExecutionState =
  | "accepted"
  | "abstained"
  | "failed"
  | "not_eligible"
  | "not_executed";

export type CommitteeStance = "supports" | "mixed" | "challenges";
export type CommitteeConfidence = "high" | "medium" | "low";

export type NumericValue = {
  value: string;
  unit: string;
  calculation_method: string;
  assumptions: string[];
  evidence_ids: string[];
  calculation_ids: string[];
};

export type MoonshotDomainPayload = {
  contract_version: "moonshot_grader_payload.v1";
  mission_relevance: "material" | "limited" | "none" | "indeterminate";
  asymmetry_assessment: "credible" | "conditional" | "not_supported" | "indeterminate";
  evidence_maturity: "clinical" | "preclinical" | "mixed" | "insufficient";
  strategic_or_societal_value: "material" | "limited" | "not_supported" | "indeterminate";
  asymmetry_drivers: string[];
  limiting_factors: string[];
};

export type CatalystDomainPayload = {
  contract_version: "catalyst_grader_payload.v1";
  catalyst_definition: string;
  programme: string;
  probability: NumericValue;
  timing_window: string;
  date_confidence: CommitteeConfidence;
  success_outcome: string;
  delay_outcome: string;
  partial_success_outcome: string;
  failure_outcome: string;
};

export type BiotechDomainPayload = {
  contract_version: "biotech_grader_payload.v1";
  mechanism_plausibility: "credible" | "mixed" | "not_supported" | "indeterminate";
  preclinical_evidence_quality: "strong" | "moderate" | "weak" | "absent";
  clinical_evidence_quality: "strong" | "moderate" | "weak" | "absent";
  trial_design_assessment: string;
  endpoint_relevance: "clinically_meaningful" | "surrogate" | "weak" | "indeterminate";
  regulatory_credibility: "credible" | "mixed" | "weak" | "indeterminate";
  claims_exceed_evidence: boolean;
  limitations: string[];
};

export type RiskDilutionDomainPayload = {
  contract_version: "risk_dilution_grader_payload.v1";
  cash_runway: NumericValue;
  burn_rate: NumericValue;
  going_concern_risk: "low" | "moderate" | "high" | "indeterminate";
  dilution_mechanisms: string[];
  financing_required_before_catalyst: "no" | "possible" | "yes" | "indeterminate";
  downside_mechanisms: string[];
  permanent_capital_loss_mechanisms: string[];
};

export type ValuationScenario = {
  scenario_id: string;
  case: "conservative" | "base" | "bull" | "failure";
  probability: NumericValue;
  equity_value: NumericValue;
  implied_value_per_diluted_share: NumericValue;
  assumptions: string[];
};

export type ValuationDomainPayload = {
  contract_version: "valuation_grader_payload.v1";
  valuation_method: string;
  current_market_value: NumericValue;
  fully_diluted_shares: NumericValue;
  scenarios: ValuationScenario[];
  sensitivities: string[];
};

export type CommitteeDomainPayload =
  | MoonshotDomainPayload
  | CatalystDomainPayload
  | BiotechDomainPayload
  | RiskDilutionDomainPayload
  | ValuationDomainPayload;

export type CommitteeMaterialClaim = {
  claim_id: string;
  claim: string;
  materiality: "high" | "medium" | "low";
  evidence_ids: string[];
};

export type CommitteeOpinion = {
  opinion_id: string;
  owned_decision_question: string;
  stance: CommitteeStance | null;
  confidence: CommitteeConfidence;
  summary: string;
  material_claims: CommitteeMaterialClaim[];
  assumptions: string[];
  contradicting_evidence: { evidence_id: string; explanation: string }[];
  evidence_gaps: { gap_id: string; description: string; required_evidence: string }[];
  invalidation_signals: string[];
  proposition: {
    proposition_id: "biotech_moonshot_catalyst_case";
    proposition_version: "biotech_moonshot_catalyst_case.v1";
    rendered_proposition_text: typeof PROPOSITION_TEXT;
    grader_stance: CommitteeStance | null;
    stance_rationale: string | null;
  };
  execution_metadata: {
    execution_id: string;
    grader_execution_contract_version: "grader_execution.v1";
    prompt_version: string;
    model_config_id: string;
    provider: string;
    model: string;
    attempt_count: number;
  };
  domain_payload: CommitteeDomainPayload;
  abstention: {
    reason_code: string;
    reason: string;
    missing_or_inadequate_evidence: string[];
    evidence_required: string[];
    confidence: CommitteeConfidence;
  } | null;
  created_at: string;
};

export type CommitteeGraderResult = {
  contract_version: "committee_grader_result.v1";
  grader_id: CommitteeGraderId;
  grader_version: string;
  grader_contract_version: string;
  output_schema_version: string;
  required: boolean;
  evidence_bundle_id: string;
  evidence_bundle_hash: string;
  execution_id: string | null;
  execution_state: CommitteeExecutionState;
  opinion: CommitteeOpinion | null;
  not_eligible: {
    eligibility_rule_version: string;
    eligibility_inputs: Record<string, string | boolean | null>;
    reason_code: string;
    reason: string;
    evaluated_at: string;
  } | null;
  not_executed: {
    reason_code: string;
    reason: string;
    gate_policy_version: string;
    failed_gate_checks: string[];
  } | null;
  failure: {
    category: "execution_failure" | "timeout" | "schema_validation" | "citation_validation" | "contract_violation" | "unsupported_output";
    attempt_count: number;
    validation_errors: string[];
    final_reason: string;
    retry_policy_version: string;
  } | null;
  persisted_at: string;
};

export type CommitteeValidationContext = {
  evidenceBundleId: string;
  evidenceBundleHash: string;
  evidenceIds: readonly string[];
  calculationIds: readonly string[];
};

const PROPOSITION_TEXT = "As of the cutoff, the available evidence supports a credible Moonshot research case with an identifiable catalyst capable of materially resolving uncertainty." as const;
const STANCES = ["supports", "mixed", "challenges"] as const;
const CONFIDENCES = ["high", "medium", "low"] as const;
const RESULT_KEYS = [
  "contract_version", "grader_id", "grader_version", "grader_contract_version",
  "output_schema_version", "required", "evidence_bundle_id",
  "evidence_bundle_hash", "execution_id", "execution_state", "opinion",
  "not_eligible", "not_executed", "failure", "persisted_at",
] as const;
const OPINION_KEYS = [
  "opinion_id", "owned_decision_question", "stance", "confidence", "summary",
  "material_claims", "assumptions", "contradicting_evidence", "evidence_gaps",
  "invalidation_signals", "proposition", "execution_metadata", "domain_payload", "abstention",
  "created_at",
] as const;
const NUMERIC_KEYS = [
  "value", "unit", "calculation_method", "assumptions", "evidence_ids",
  "calculation_ids",
] as const;

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

function boolean(value: unknown, label: string) {
  if (typeof value !== "boolean") throw new TypeError(`invalid ${label}`);
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
  if (typeof value !== "string" || Number.isNaN(Date.parse(value))) throw new TypeError(`invalid ${label}`);
}

function parseNumericValue(value: unknown, label: string, context: CommitteeValidationContext): NumericValue {
  const numeric = record(value, label);
  exactKeys(numeric, NUMERIC_KEYS, label);
  if (typeof numeric.value !== "string" || !/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(numeric.value)) throw new TypeError(`invalid ${label}.value`);
  string(numeric.unit, `${label}.unit`);
  string(numeric.calculation_method, `${label}.calculation_method`);
  strings(numeric.assumptions, `${label}.assumptions`);
  const evidenceIds = strings(numeric.evidence_ids, `${label}.evidence_ids`);
  const calculationIds = strings(numeric.calculation_ids, `${label}.calculation_ids`);
  if (evidenceIds.length + calculationIds.length === 0) throw new TypeError(`invalid ${label} supporting references`);
  const allowedEvidence = new Set(context.evidenceIds);
  const allowedCalculations = new Set(context.calculationIds);
  for (const id of evidenceIds) if (!allowedEvidence.has(id)) throw new TypeError(`unresolved evidence citation ${id}`);
  for (const id of calculationIds) if (!allowedCalculations.has(id)) throw new TypeError(`unresolved calculation reference ${id}`);
  return numeric as NumericValue;
}

export function parseCommitteeDomainPayload(graderId: CommitteeGraderId, value: unknown, context: CommitteeValidationContext): CommitteeDomainPayload {
  const payload = record(value, "opinion.domain_payload");
  if (graderId === "moonshot") {
    exactKeys(payload, ["contract_version", "mission_relevance", "asymmetry_assessment", "evidence_maturity", "strategic_or_societal_value", "asymmetry_drivers", "limiting_factors"], "opinion.domain_payload");
    oneOf(payload.contract_version, ["moonshot_grader_payload.v1"], "opinion.domain_payload.contract_version");
    oneOf(payload.mission_relevance, ["material", "limited", "none", "indeterminate"], "opinion.domain_payload.mission_relevance");
    oneOf(payload.asymmetry_assessment, ["credible", "conditional", "not_supported", "indeterminate"], "opinion.domain_payload.asymmetry_assessment");
    oneOf(payload.evidence_maturity, ["clinical", "preclinical", "mixed", "insufficient"], "opinion.domain_payload.evidence_maturity");
    oneOf(payload.strategic_or_societal_value, ["material", "limited", "not_supported", "indeterminate"], "opinion.domain_payload.strategic_or_societal_value");
    strings(payload.asymmetry_drivers, "opinion.domain_payload.asymmetry_drivers");
    strings(payload.limiting_factors, "opinion.domain_payload.limiting_factors");
  } else if (graderId === "catalyst") {
    exactKeys(payload, ["contract_version", "catalyst_definition", "programme", "probability", "timing_window", "date_confidence", "success_outcome", "delay_outcome", "partial_success_outcome", "failure_outcome"], "opinion.domain_payload");
    oneOf(payload.contract_version, ["catalyst_grader_payload.v1"], "opinion.domain_payload.contract_version");
    for (const key of ["catalyst_definition", "programme", "timing_window", "success_outcome", "delay_outcome", "partial_success_outcome", "failure_outcome"]) string(payload[key], `opinion.domain_payload.${key}`);
    parseNumericValue(payload.probability, "opinion.domain_payload.probability", context);
    oneOf(payload.date_confidence, CONFIDENCES, "opinion.domain_payload.date_confidence");
  } else if (graderId === "biotech") {
    exactKeys(payload, ["contract_version", "mechanism_plausibility", "preclinical_evidence_quality", "clinical_evidence_quality", "trial_design_assessment", "endpoint_relevance", "regulatory_credibility", "claims_exceed_evidence", "limitations"], "opinion.domain_payload");
    oneOf(payload.contract_version, ["biotech_grader_payload.v1"], "opinion.domain_payload.contract_version");
    oneOf(payload.mechanism_plausibility, ["credible", "mixed", "not_supported", "indeterminate"], "opinion.domain_payload.mechanism_plausibility");
    oneOf(payload.preclinical_evidence_quality, ["strong", "moderate", "weak", "absent"], "opinion.domain_payload.preclinical_evidence_quality");
    oneOf(payload.clinical_evidence_quality, ["strong", "moderate", "weak", "absent"], "opinion.domain_payload.clinical_evidence_quality");
    string(payload.trial_design_assessment, "opinion.domain_payload.trial_design_assessment");
    oneOf(payload.endpoint_relevance, ["clinically_meaningful", "surrogate", "weak", "indeterminate"], "opinion.domain_payload.endpoint_relevance");
    oneOf(payload.regulatory_credibility, ["credible", "mixed", "weak", "indeterminate"], "opinion.domain_payload.regulatory_credibility");
    boolean(payload.claims_exceed_evidence, "opinion.domain_payload.claims_exceed_evidence");
    strings(payload.limitations, "opinion.domain_payload.limitations");
  } else if (graderId === "risk_dilution") {
    exactKeys(payload, ["contract_version", "cash_runway", "burn_rate", "going_concern_risk", "dilution_mechanisms", "financing_required_before_catalyst", "downside_mechanisms", "permanent_capital_loss_mechanisms"], "opinion.domain_payload");
    oneOf(payload.contract_version, ["risk_dilution_grader_payload.v1"], "opinion.domain_payload.contract_version");
    parseNumericValue(payload.cash_runway, "opinion.domain_payload.cash_runway", context);
    parseNumericValue(payload.burn_rate, "opinion.domain_payload.burn_rate", context);
    oneOf(payload.going_concern_risk, ["low", "moderate", "high", "indeterminate"], "opinion.domain_payload.going_concern_risk");
    oneOf(payload.financing_required_before_catalyst, ["no", "possible", "yes", "indeterminate"], "opinion.domain_payload.financing_required_before_catalyst");
    for (const key of ["dilution_mechanisms", "downside_mechanisms", "permanent_capital_loss_mechanisms"]) strings(payload[key], `opinion.domain_payload.${key}`);
  } else {
    exactKeys(payload, ["contract_version", "valuation_method", "current_market_value", "fully_diluted_shares", "scenarios", "sensitivities"], "opinion.domain_payload");
    oneOf(payload.contract_version, ["valuation_grader_payload.v1"], "opinion.domain_payload.contract_version");
    string(payload.valuation_method, "opinion.domain_payload.valuation_method");
    parseNumericValue(payload.current_market_value, "opinion.domain_payload.current_market_value", context);
    parseNumericValue(payload.fully_diluted_shares, "opinion.domain_payload.fully_diluted_shares", context);
    if (!Array.isArray(payload.scenarios) || payload.scenarios.length !== 4) throw new TypeError("invalid opinion.domain_payload.scenarios");
    const cases = new Set<string>();
    payload.scenarios.forEach((candidate, index) => {
      const scenario = record(candidate, `opinion.domain_payload.scenarios[${index}]`);
      exactKeys(scenario, ["scenario_id", "case", "probability", "equity_value", "implied_value_per_diluted_share", "assumptions"], `opinion.domain_payload.scenarios[${index}]`);
      string(scenario.scenario_id, `opinion.domain_payload.scenarios[${index}].scenario_id`);
      oneOf(scenario.case, ["conservative", "base", "bull", "failure"], `opinion.domain_payload.scenarios[${index}].case`);
      if (cases.has(scenario.case as string)) throw new TypeError("duplicate valuation scenario case");
      cases.add(scenario.case as string);
      parseNumericValue(scenario.probability, `opinion.domain_payload.scenarios[${index}].probability`, context);
      parseNumericValue(scenario.equity_value, `opinion.domain_payload.scenarios[${index}].equity_value`, context);
      parseNumericValue(scenario.implied_value_per_diluted_share, `opinion.domain_payload.scenarios[${index}].implied_value_per_diluted_share`, context);
      strings(scenario.assumptions, `opinion.domain_payload.scenarios[${index}].assumptions`);
    });
    if (cases.size !== 4) throw new TypeError("missing valuation scenario case");
    strings(payload.sensitivities, "opinion.domain_payload.sensitivities");
  }
  return payload as CommitteeDomainPayload;
}

function parseOpinion(graderId: CommitteeGraderId, value: unknown, context: CommitteeValidationContext): CommitteeOpinion {
  const opinion = record(value, "opinion");
  exactKeys(opinion, OPINION_KEYS, "opinion");
  uuid(opinion.opinion_id, "opinion.opinion_id");
  const definition = MVP_COMMITTEE_ROSTER.find((candidate) => candidate.grader_id === graderId)!;
  if (opinion.owned_decision_question !== definition.owned_decision_question) throw new TypeError("invalid owned decision question");
  if (opinion.stance !== null) oneOf(opinion.stance, STANCES, "opinion.stance");
  oneOf(opinion.confidence, CONFIDENCES, "opinion.confidence");
  string(opinion.summary, "opinion.summary");
  if (!Array.isArray(opinion.material_claims)) throw new TypeError("invalid opinion.material_claims");
  const allowedEvidence = new Set(context.evidenceIds);
  opinion.material_claims.forEach((candidate, index) => {
    const claim = record(candidate, `opinion.material_claims[${index}]`);
    exactKeys(claim, ["claim_id", "claim", "materiality", "evidence_ids"], `opinion.material_claims[${index}]`);
    string(claim.claim_id, `opinion.material_claims[${index}].claim_id`);
    string(claim.claim, `opinion.material_claims[${index}].claim`);
    oneOf(claim.materiality, ["high", "medium", "low"], `opinion.material_claims[${index}].materiality`);
    for (const id of strings(claim.evidence_ids, `opinion.material_claims[${index}].evidence_ids`, false)) if (!allowedEvidence.has(id)) throw new TypeError(`unresolved evidence citation ${id}`);
  });
  strings(opinion.assumptions, "opinion.assumptions");
  if (!Array.isArray(opinion.contradicting_evidence)) throw new TypeError("invalid opinion.contradicting_evidence");
  opinion.contradicting_evidence.forEach((candidate, index) => {
    const item = record(candidate, `opinion.contradicting_evidence[${index}]`);
    exactKeys(item, ["evidence_id", "explanation"], `opinion.contradicting_evidence[${index}]`);
    string(item.evidence_id, `opinion.contradicting_evidence[${index}].evidence_id`);
    string(item.explanation, `opinion.contradicting_evidence[${index}].explanation`);
    if (!allowedEvidence.has(item.evidence_id as string)) throw new TypeError(`unresolved evidence citation ${item.evidence_id}`);
  });
  if (!Array.isArray(opinion.evidence_gaps)) throw new TypeError("invalid opinion.evidence_gaps");
  opinion.evidence_gaps.forEach((candidate, index) => {
    const gap = record(candidate, `opinion.evidence_gaps[${index}]`);
    exactKeys(gap, ["gap_id", "description", "required_evidence"], `opinion.evidence_gaps[${index}]`);
    for (const key of ["gap_id", "description", "required_evidence"]) string(gap[key], `opinion.evidence_gaps[${index}].${key}`);
  });
  strings(opinion.invalidation_signals, "opinion.invalidation_signals");
  const proposition = record(opinion.proposition, "opinion.proposition");
  exactKeys(proposition, ["proposition_id", "proposition_version", "rendered_proposition_text", "grader_stance", "stance_rationale"], "opinion.proposition");
  if (proposition.proposition_id !== "biotech_moonshot_catalyst_case" || proposition.proposition_version !== "biotech_moonshot_catalyst_case.v1" || proposition.rendered_proposition_text !== PROPOSITION_TEXT) throw new TypeError("invalid proposition identity");
  if (proposition.grader_stance !== null) oneOf(proposition.grader_stance, STANCES, "opinion.proposition.grader_stance");
  if (proposition.stance_rationale !== null) string(proposition.stance_rationale, "opinion.proposition.stance_rationale");
  const metadata = record(opinion.execution_metadata, "opinion.execution_metadata");
  exactKeys(metadata, ["execution_id", "grader_execution_contract_version", "prompt_version", "model_config_id", "provider", "model", "attempt_count"], "opinion.execution_metadata");
  uuid(metadata.execution_id, "opinion.execution_metadata.execution_id");
  oneOf(metadata.grader_execution_contract_version, ["grader_execution.v1"], "opinion.execution_metadata.grader_execution_contract_version");
  for (const key of ["prompt_version", "model_config_id", "provider", "model"]) string(metadata[key], `opinion.execution_metadata.${key}`);
  if (!Number.isSafeInteger(metadata.attempt_count) || (metadata.attempt_count as number) < 1 || (metadata.attempt_count as number) > 2) throw new TypeError("invalid opinion.execution_metadata.attempt_count");
  parseCommitteeDomainPayload(graderId, opinion.domain_payload, context);
  if (opinion.abstention !== null) {
    const abstention = record(opinion.abstention, "opinion.abstention");
    exactKeys(abstention, ["reason_code", "reason", "missing_or_inadequate_evidence", "evidence_required", "confidence"], "opinion.abstention");
    string(abstention.reason_code, "opinion.abstention.reason_code");
    string(abstention.reason, "opinion.abstention.reason");
    strings(abstention.missing_or_inadequate_evidence, "opinion.abstention.missing_or_inadequate_evidence", false);
    strings(abstention.evidence_required, "opinion.abstention.evidence_required", false);
    oneOf(abstention.confidence, CONFIDENCES, "opinion.abstention.confidence");
  }
  timestamp(opinion.created_at, "opinion.created_at");
  return opinion as CommitteeOpinion;
}

export function parseCommitteeGraderResult(value: unknown, context: CommitteeValidationContext): CommitteeGraderResult {
  const result = record(value, "committee grader result");
  exactKeys(result, RESULT_KEYS, "committee grader result");
  oneOf(result.contract_version, ["committee_grader_result.v1"], "contract_version");
  oneOf(result.grader_id, MVP_COMMITTEE_ROSTER.map((grader) => grader.grader_id), "grader_id");
  const graderId = result.grader_id as CommitteeGraderId;
  const definition = MVP_COMMITTEE_ROSTER.find((candidate) => candidate.grader_id === graderId)!;
  if (result.grader_version !== definition.grader_version || result.grader_contract_version !== definition.grader_contract_version || result.output_schema_version !== definition.output_schema_version) throw new TypeError("invalid grader contract identity");
  if (result.required !== true) throw new TypeError("eligible MVP grader must be required");
  uuid(result.evidence_bundle_id, "evidence_bundle_id");
  hash(result.evidence_bundle_hash, "evidence_bundle_hash");
  if (result.evidence_bundle_id !== context.evidenceBundleId || result.evidence_bundle_hash !== context.evidenceBundleHash) throw new TypeError("grader result bundle identity mismatch");
  if (result.execution_id !== null) uuid(result.execution_id, "execution_id");
  oneOf(result.execution_state, ["accepted", "abstained", "failed", "not_eligible", "not_executed"], "execution_state");
  timestamp(result.persisted_at, "persisted_at");
  const opinion = result.opinion === null ? null : parseOpinion(graderId, result.opinion, context);

  if (result.execution_state === "accepted" || result.execution_state === "abstained") {
    if (result.execution_id === null || opinion === null || result.not_eligible !== null || result.not_executed !== null || result.failure !== null) throw new TypeError(`invalid ${result.execution_state} grader result`);
    if (opinion.execution_metadata.execution_id !== result.execution_id) throw new TypeError("opinion execution metadata mismatch");
    const proposition = opinion.proposition;
    if (result.execution_state === "accepted") {
      if (opinion.stance === null || proposition.grader_stance !== opinion.stance || proposition.stance_rationale === null || opinion.abstention !== null) throw new TypeError("invalid accepted grader result");
    } else if (opinion.stance !== null || proposition.grader_stance !== null || proposition.stance_rationale !== null || opinion.abstention === null) {
      throw new TypeError("invalid abstained grader result");
    }
  } else if (result.execution_state === "not_eligible") {
    if (result.execution_id !== null || opinion !== null || result.not_eligible === null || result.not_executed !== null || result.failure !== null) throw new TypeError("invalid not_eligible grader result");
    const detail = record(result.not_eligible, "not_eligible");
    exactKeys(detail, ["eligibility_rule_version", "eligibility_inputs", "reason_code", "reason", "evaluated_at"], "not_eligible");
    string(detail.eligibility_rule_version, "not_eligible.eligibility_rule_version");
    const inputs = record(detail.eligibility_inputs, "not_eligible.eligibility_inputs");
    if (Object.keys(inputs).some((key) => key.length === 0 || !["string", "boolean"].includes(typeof inputs[key]) && inputs[key] !== null)) throw new TypeError("invalid not_eligible.eligibility_inputs");
    string(detail.reason_code, "not_eligible.reason_code");
    string(detail.reason, "not_eligible.reason");
    timestamp(detail.evaluated_at, "not_eligible.evaluated_at");
  } else if (result.execution_state === "not_executed") {
    if (result.execution_id !== null || opinion !== null || result.not_eligible !== null || result.not_executed === null || result.failure !== null) throw new TypeError("invalid not_executed grader result");
    const detail = record(result.not_executed, "not_executed");
    exactKeys(detail, ["reason_code", "reason", "gate_policy_version", "failed_gate_checks"], "not_executed");
    for (const key of ["reason_code", "reason", "gate_policy_version"]) string(detail[key], `not_executed.${key}`);
    strings(detail.failed_gate_checks, "not_executed.failed_gate_checks", false);
  } else {
    if (result.execution_id === null || opinion !== null || result.not_eligible !== null || result.not_executed !== null || result.failure === null) throw new TypeError("invalid failed grader result");
    const detail = record(result.failure, "failure");
    exactKeys(detail, ["category", "attempt_count", "validation_errors", "final_reason", "retry_policy_version"], "failure");
    oneOf(detail.category, ["execution_failure", "timeout", "schema_validation", "citation_validation", "contract_violation", "unsupported_output"], "failure.category");
    if (!Number.isSafeInteger(detail.attempt_count) || (detail.attempt_count as number) < 1 || (detail.attempt_count as number) > 2) throw new TypeError("invalid failure.attempt_count");
    strings(detail.validation_errors, "failure.validation_errors");
    string(detail.final_reason, "failure.final_reason");
    string(detail.retry_policy_version, "failure.retry_policy_version");
  }
  return result as CommitteeGraderResult;
}

export type CommitteeStatus =
  | "complete"
  | "complete_with_abstentions"
  | "incomplete_required_grader_failed"
  | "insufficient_accepted_opinions";

export type CommitteeState = {
  contract_version: "committee_state.v1";
  research_run_id: string;
  evidence_bundle_id: string;
  evidence_bundle_hash: string;
  workflow_config_version: string;
  proposition_id: "biotech_moonshot_catalyst_case";
  proposition_version: "biotech_moonshot_catalyst_case.v1";
  rendered_proposition_text: typeof PROPOSITION_TEXT;
  committee_status: CommitteeStatus;
  accounting: {
    eligible_count: number;
    accepted_count: number;
    abstained_count: number;
    not_eligible_count: number;
    failed_count: number;
    not_executed_count: number;
  };
  stance_counts: Record<CommitteeStance, number>;
  stance_matrix: {
    grader_id: CommitteeGraderId;
    opinion_id: string;
    stance: CommitteeStance;
    stance_rationale: string;
  }[];
  grader_results: CommitteeGraderResult[];
  derived_at: string;
};

export type CommitteeDerivationContext = CommitteeValidationContext & {
  researchRunId: string;
  workflowConfigVersion: string;
  derivedAt: string;
};

export function deriveCommitteeState(
  values: readonly unknown[],
  context: CommitteeDerivationContext,
): CommitteeState {
  uuid(context.researchRunId, "researchRunId");
  string(context.workflowConfigVersion, "workflowConfigVersion");
  timestamp(context.derivedAt, "derivedAt");
  if (values.length !== MVP_COMMITTEE_ROSTER.length) throw new TypeError("committee requires exactly five grader results");
  const byGrader = new Map<CommitteeGraderId, CommitteeGraderResult>();
  const executionIds = new Set<string>();
  const opinionIds = new Set<string>();
  for (const value of values) {
    const result = parseCommitteeGraderResult(value, context);
    if (byGrader.has(result.grader_id)) throw new TypeError("duplicate committee grader result");
    if (Date.parse(result.persisted_at) >= Date.parse(context.derivedAt)) throw new TypeError("grader result must persist before committee derivation");
    if (result.execution_id !== null) {
      if (executionIds.has(result.execution_id)) throw new TypeError("duplicate execution identity");
      executionIds.add(result.execution_id);
    }
    if (result.opinion !== null) {
      if (opinionIds.has(result.opinion.opinion_id)) throw new TypeError("duplicate opinion identity");
      opinionIds.add(result.opinion.opinion_id);
    }
    byGrader.set(result.grader_id, result);
  }
  const graderResults = MVP_COMMITTEE_ROSTER.map((definition) => {
    const result = byGrader.get(definition.grader_id);
    if (!result) throw new TypeError(`missing committee grader ${definition.grader_id}`);
    return result;
  });
  const count = (state: CommitteeExecutionState) => graderResults.filter((result) => result.execution_state === state).length;
  const acceptedCount = count("accepted");
  const abstainedCount = count("abstained");
  const notEligibleCount = count("not_eligible");
  const failedCount = count("failed");
  const notExecutedCount = count("not_executed");
  const eligibleCount = graderResults.length - notEligibleCount;
  const committeeStatus: CommitteeStatus = failedCount > 0
    ? "incomplete_required_grader_failed"
    : eligibleCount === 0 || notExecutedCount > 0
      ? "insufficient_accepted_opinions"
      : abstainedCount > 0
        ? "complete_with_abstentions"
        : acceptedCount === eligibleCount
          ? "complete"
          : "insufficient_accepted_opinions";
  const stanceMatrix = graderResults.flatMap((result) => {
    const opinion = result.opinion;
    if (result.execution_state !== "accepted" || opinion === null || opinion.stance === null || opinion.proposition.stance_rationale === null) return [];
    return [{
      grader_id: result.grader_id,
      opinion_id: opinion.opinion_id,
      stance: opinion.stance,
      stance_rationale: opinion.proposition.stance_rationale,
    }];
  });
  const stanceCounts = stanceMatrix.reduce<Record<CommitteeStance, number>>(
    (counts, entry) => ({ ...counts, [entry.stance]: counts[entry.stance] + 1 }),
    { supports: 0, mixed: 0, challenges: 0 },
  );
  return {
    contract_version: "committee_state.v1",
    research_run_id: context.researchRunId,
    evidence_bundle_id: context.evidenceBundleId,
    evidence_bundle_hash: context.evidenceBundleHash,
    workflow_config_version: context.workflowConfigVersion,
    proposition_id: "biotech_moonshot_catalyst_case",
    proposition_version: "biotech_moonshot_catalyst_case.v1",
    rendered_proposition_text: PROPOSITION_TEXT,
    committee_status: committeeStatus,
    accounting: {
      eligible_count: eligibleCount,
      accepted_count: acceptedCount,
      abstained_count: abstainedCount,
      not_eligible_count: notEligibleCount,
      failed_count: failedCount,
      not_executed_count: notExecutedCount,
    },
    stance_counts: stanceCounts,
    stance_matrix: stanceMatrix,
    grader_results: graderResults,
    derived_at: context.derivedAt,
  };
}

const COMMITTEE_STATE_KEYS = [
  "contract_version", "research_run_id", "evidence_bundle_id",
  "evidence_bundle_hash", "workflow_config_version", "proposition_id",
  "proposition_version", "rendered_proposition_text", "committee_status",
  "accounting", "stance_counts", "stance_matrix", "grader_results",
  "derived_at",
] as const;

function canonicalValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalValue(item)]),
    );
  }
  return value;
}

export function parseCommitteeState(
  value: unknown,
  context: CommitteeValidationContext,
): CommitteeState {
  const state = record(value, "committee state");
  exactKeys(state, COMMITTEE_STATE_KEYS, "committee state");
  oneOf(state.contract_version, ["committee_state.v1"], "contract_version");
  uuid(state.research_run_id, "research_run_id");
  uuid(state.evidence_bundle_id, "evidence_bundle_id");
  hash(state.evidence_bundle_hash, "evidence_bundle_hash");
  string(state.workflow_config_version, "workflow_config_version");
  if (state.evidence_bundle_id !== context.evidenceBundleId || state.evidence_bundle_hash !== context.evidenceBundleHash) throw new TypeError("committee state bundle identity mismatch");
  if (!Array.isArray(state.grader_results)) throw new TypeError("invalid grader_results");
  const derived = deriveCommitteeState(state.grader_results, {
    ...context,
    researchRunId: state.research_run_id as string,
    workflowConfigVersion: state.workflow_config_version as string,
    derivedAt: state.derived_at as string,
  });
  if (JSON.stringify(canonicalValue(state)) !== JSON.stringify(canonicalValue(derived))) {
    throw new TypeError("committee state does not match deterministic derivation");
  }
  return state as CommitteeState;
}
