import type {
  EvidenceBundle,
  ExecutionCost,
  GraderAttempt,
  GraderExecution,
  GraderOpinion,
  NumericValue,
  ResearchRun,
  TokenUsage,
} from "@iros/types";

type StateVariant = "verified" | "attention" | "destructive";

function humanize(value: string) {
  const words = value.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function formatTokens(value: number) {
  return value.toLocaleString("en");
}

function presentUsage(usage: TokenUsage) {
  return {
    inputTokens: formatTokens(usage.input_tokens),
    cachedInputTokens: formatTokens(usage.cached_input_tokens),
    uncachedInputTokens: formatTokens(usage.uncached_input_tokens),
    outputTokens: formatTokens(usage.output_tokens),
    reasoningTokens: formatTokens(usage.reasoning_tokens),
    totalTokens: formatTokens(usage.total_tokens),
    toolCalls: formatTokens(usage.tool_call_count),
    completeness: usage.usage_complete ? "Complete" : "Incomplete",
  };
}

function presentCost(cost: ExecutionCost) {
  return {
    reserved: `${cost.currency} ${cost.reserved_cost_usd}`,
    estimated: `${cost.currency} ${cost.estimated_cost_usd}`,
    billed:
      cost.billed_cost_usd === null
        ? "Not available"
        : `${cost.currency} ${cost.billed_cost_usd}`,
    priceCard: cost.price_card_version,
  };
}

function executionStatus(state: GraderExecution["execution_state"]): {
  label: "Accepted" | "Abstained" | "Failed" | "Not executed";
  variant: StateVariant;
} {
  if (state === "accepted") return { label: "Accepted", variant: "verified" };
  if (state === "failed") return { label: "Failed", variant: "destructive" };
  if (state === "abstained") return { label: "Abstained", variant: "attention" };
  return { label: "Not executed", variant: "attention" };
}

function validationStatus(attempt: GraderAttempt) {
  if (attempt.validation.status === "passed") {
    return { label: "Validated" as const, variant: "verified" as const };
  }
  if (attempt.validation.status === "failed") {
    return { label: "Validation failed" as const, variant: "destructive" as const };
  }
  return { label: "Not validated" as const, variant: "attention" as const };
}

function attemptStatus(attempt: GraderAttempt): {
  label: string;
  variant: StateVariant;
} {
  if (attempt.result === "accepted") {
    return { label: "Accepted", variant: "verified" };
  }
  if (attempt.result === "abstained") {
    return { label: "Abstained", variant: "attention" };
  }
  return { label: humanize(attempt.result), variant: "destructive" };
}

function validationFlag(value: boolean | null) {
  if (value === null) return "Not run";
  return value ? "Pass" : "Fail";
}

function stancePresentation(stance: GraderOpinion["stance"]): {
  label: "Supports" | "Mixed" | "Challenges" | "No stance";
  variant: StateVariant;
} {
  switch (stance) {
    case "supports":
      return { label: "Supports", variant: "verified" };
    case "mixed":
      return { label: "Mixed", variant: "attention" };
    case "challenges":
      return { label: "Challenges", variant: "destructive" };
    default:
      return { label: "No stance", variant: "attention" };
  }
}

type DomainField = { label: string; value: string };
type DomainSection = { title: string; items: string[] };

function numericFields(label: string, numeric: NumericValue): DomainField[] {
  return [
    { label, value: `${numeric.value} ${numeric.unit}` },
    { label: `${label} method`, value: numeric.calculation_method },
  ];
}

function numericSections(label: string, numeric: NumericValue): DomainSection[] {
  return [
    { title: `${label} assumptions`, items: numeric.assumptions },
    { title: `${label} evidence`, items: numeric.evidence_ids },
    { title: `${label} calculations`, items: numeric.calculation_ids },
  ];
}

function presentDomain(opinion: GraderOpinion): {
  title: string;
  fields: DomainField[];
  sections: DomainSection[];
} {
  switch (opinion.grader_id) {
    case "moonshot":
      return {
        title: "Moonshot rubric result",
        fields: [
          { label: "Mission relevance", value: humanize(opinion.moonshot_payload.mission_relevance) },
          { label: "Asymmetry", value: humanize(opinion.moonshot_payload.asymmetry_assessment) },
          { label: "Evidence maturity", value: humanize(opinion.moonshot_payload.evidence_maturity) },
          { label: "Strategic value", value: humanize(opinion.moonshot_payload.strategic_or_societal_value) },
        ],
        sections: [
          { title: "Asymmetry drivers", items: opinion.moonshot_payload.asymmetry_drivers },
          { title: "Limiting factors", items: opinion.moonshot_payload.limiting_factors },
        ],
      };
    case "catalyst": {
      const payload = opinion.catalyst_payload;
      return {
        title: "Catalyst rubric result",
        fields: [
          { label: "Catalyst", value: payload.catalyst_definition },
          { label: "Programme", value: payload.programme },
          ...numericFields("Probability", payload.probability),
          { label: "Timing window", value: payload.timing_window },
          { label: "Date confidence", value: humanize(payload.date_confidence) },
          { label: "Success outcome", value: payload.success_outcome },
          { label: "Delay outcome", value: payload.delay_outcome },
          { label: "Partial-success outcome", value: payload.partial_success_outcome },
          { label: "Failure outcome", value: payload.failure_outcome },
        ],
        sections: numericSections("Probability", payload.probability),
      };
    }
    case "biotech": {
      const payload = opinion.biotech_payload;
      return {
        title: "Biotech rubric result",
        fields: [
          { label: "Mechanism plausibility", value: humanize(payload.mechanism_plausibility) },
          { label: "Preclinical evidence", value: humanize(payload.preclinical_evidence_quality) },
          { label: "Clinical evidence", value: humanize(payload.clinical_evidence_quality) },
          { label: "Trial design", value: payload.trial_design_assessment },
          { label: "Endpoint relevance", value: humanize(payload.endpoint_relevance) },
          { label: "Regulatory credibility", value: humanize(payload.regulatory_credibility) },
          { label: "Claims exceed evidence", value: payload.claims_exceed_evidence ? "Yes" : "No" },
        ],
        sections: [{ title: "Limitations", items: payload.limitations }],
      };
    }
    case "risk_dilution": {
      const payload = opinion.risk_dilution_payload;
      return {
        title: "Risk/Dilution rubric result",
        fields: [
          ...numericFields("Cash runway", payload.cash_runway),
          ...numericFields("Burn rate", payload.burn_rate),
          { label: "Going-concern risk", value: humanize(payload.going_concern_risk) },
          { label: "Financing before catalyst", value: humanize(payload.financing_required_before_catalyst) },
        ],
        sections: [
          ...numericSections("Cash runway", payload.cash_runway),
          ...numericSections("Burn rate", payload.burn_rate),
          { title: "Dilution mechanisms", items: payload.dilution_mechanisms },
          { title: "Downside mechanisms", items: payload.downside_mechanisms },
          { title: "Permanent-capital-loss mechanisms", items: payload.permanent_capital_loss_mechanisms },
        ],
      };
    }
    case "valuation": {
      const payload = opinion.valuation_payload;
      return {
        title: "Valuation rubric result",
        fields: [
          { label: "Method", value: payload.valuation_method },
          ...numericFields("Current market value", payload.current_market_value),
          ...numericFields("Fully diluted shares", payload.fully_diluted_shares),
          ...payload.scenarios.flatMap((scenario) => [
            ...numericFields(`${humanize(scenario.case)} probability`, scenario.probability),
            ...numericFields(`${humanize(scenario.case)} equity value`, scenario.equity_value),
            ...numericFields(`${humanize(scenario.case)} diluted-share value`, scenario.implied_value_per_diluted_share),
          ]),
        ],
        sections: [
          ...numericSections("Current market value", payload.current_market_value),
          ...numericSections("Fully diluted shares", payload.fully_diluted_shares),
          ...payload.scenarios.flatMap((scenario) => [
            { title: `${humanize(scenario.case)} assumptions`, items: scenario.assumptions },
            ...numericSections(`${humanize(scenario.case)} probability`, scenario.probability),
            ...numericSections(`${humanize(scenario.case)} equity value`, scenario.equity_value),
            ...numericSections(`${humanize(scenario.case)} diluted-share value`, scenario.implied_value_per_diluted_share),
          ]),
          { title: "Sensitivities", items: payload.sensitivities },
        ],
      };
    }
  }
}

function presentOpinion(opinion: GraderOpinion | null) {
  if (opinion === null) return null;

  return {
    stance: stancePresentation(opinion.stance),
    id: opinion.opinion_id,
    ownedQuestion: opinion.owned_decision_question,
    confidence: opinion.confidence,
    summary: opinion.summary,
    abstention:
      opinion.abstention === null
        ? null
        : {
            reasonCode: opinion.abstention.reason_code,
            reason: opinion.abstention.reason,
            missingEvidence: opinion.abstention.missing_or_inadequate_evidence,
            evidenceRequired: opinion.abstention.evidence_required,
            confidence: opinion.abstention.confidence,
          },
    claims: opinion.material_claims.map((claim) => ({
      id: claim.claim_id,
      claim: claim.claim,
      materiality: claim.materiality,
      evidenceIds: claim.evidence_ids,
    })),
    proposition: {
      id: opinion.proposition.proposition_id,
      version: opinion.proposition.proposition_version,
      text: opinion.proposition.rendered_proposition_text,
      rationale: opinion.proposition.stance_rationale,
    },
    assumptions: opinion.assumptions,
    contradictions: opinion.contradicting_evidence.map((item) => ({
      evidenceId: item.evidence_id,
      explanation: item.explanation,
    })),
    gaps: opinion.evidence_gaps.map((gap) => ({
      id: gap.gap_id,
      description: gap.description,
      requiredEvidence: gap.required_evidence,
    })),
    invalidationSignals: opinion.invalidation_signals,
    domain: presentDomain(opinion),
  };
}

function presentOutcome(execution: GraderExecution) {
  if (execution.not_executed !== null) {
    return {
      kind: "not_executed" as const,
      reasonCode: execution.not_executed.reason_code,
      reason: execution.not_executed.reason,
      policy: execution.not_executed.gate_policy_version,
      failedChecks: execution.not_executed.failed_gate_checks,
    };
  }
  if (execution.failure !== null) {
    return {
      kind: "failed" as const,
      category: execution.failure.category,
      attemptCount: execution.failure.attempt_count,
      validationErrors: execution.failure.validation_errors,
      finalReason: execution.failure.final_reason,
      retryPolicy: execution.failure.retry_policy_version,
    };
  }
  return null;
}

function presentExecution(execution: GraderExecution) {
  return {
    status: executionStatus(execution.execution_state),
    identity: {
      id: execution.id,
      executionKey: execution.execution_key,
      grader: execution.grader_id,
      graderVersion: execution.grader_version,
      required: execution.required ? "Required" : "Optional",
      bundleId: execution.evidence_bundle_id,
      bundleHash: execution.evidence_bundle_hash,
      started: execution.started_at,
      finished: execution.finished_at,
    },
    configuration: {
      provider: execution.provider,
      model: execution.model,
      modelConfig: execution.model_config_id,
      prompt: execution.prompt_version,
      graderContract: execution.grader_contract_version,
      eligibilityRule: execution.eligibility_rule_version,
      rubric: execution.rubric_version,
      outputSchema: execution.output_schema_version,
      abstentionRules: execution.abstention_rules_version,
      retryPolicy: execution.retry_policy_version,
      inferenceParameters: execution.inference_parameter_hash,
    },
    gate: {
      status:
        execution.pre_call_gate.status === "passed"
          ? { label: "Passed" as const, variant: "verified" as const }
          : { label: "Blocked" as const, variant: "attention" as const },
      policy: execution.pre_call_gate.policy_version,
      checked: execution.pre_call_gate.checked_at,
      checks: execution.pre_call_gate.checks.map((check) => ({
        id: check.check_id,
        label: humanize(check.check_id),
        passed: check.passed,
        reason: check.reason_code,
        status: check.passed
          ? { label: "Pass" as const, variant: "verified" as const }
          : { label: "Fail" as const, variant: "destructive" as const },
      })),
    },
    budget: {
      status: execution.budget.status,
      policy: execution.budget.budget_policy_version,
      reserved: `${execution.budget.currency} ${execution.budget.reserved_cost_usd}`,
      reconciled:
        execution.budget.reconciled_cost_usd === null
          ? "Not available"
          : `${execution.budget.currency} ${execution.budget.reconciled_cost_usd}`,
    },
    usage: presentUsage(execution.total_usage),
    cost: presentCost(execution.total_cost),
    attempts: execution.attempts.map((attempt) => ({
      id: attempt.attempt_id,
      number: attempt.attempt_number,
      result: attempt.result,
      status: attemptStatus(attempt),
      requestHash: attempt.request_sha256,
      provider: attempt.provider,
      model: attempt.model,
      modelConfig: attempt.model_config_id,
      prompt: attempt.prompt_version,
      started: attempt.started_at,
      finished: attempt.finished_at,
      duration: `${formatTokens(attempt.duration_ms)} ms`,
      retryReason: attempt.retry_reason,
      validation: {
        ...validationStatus(attempt),
        schema: validationFlag(attempt.validation.schema_valid),
        citations: validationFlag(attempt.validation.citations_valid),
        errors: attempt.validation.errors,
      },
      usage: presentUsage(attempt.usage),
      cost: presentCost(attempt.cost),
      rawOutputState:
        attempt.raw_payload_id === null
          ? "No provider output stored"
          : "Stored in restricted audit record",
    })),
    outcome: presentOutcome(execution),
    opinion: presentOpinion(execution.opinion),
  };
}

export function presentGraderExecutionWorkspace(
  run: ResearchRun,
  bundle: EvidenceBundle | null,
  executions: GraderExecution[],
) {
  if (bundle === null) {
    return {
      kind: "missing" as const,
      description:
        "Frozen Evidence Bundle must exist before grader executions can be audited.",
      status: { label: "Not available" as const, variant: "attention" as const },
    };
  }
  if (executions.length === 0) {
    return {
      kind: "missing" as const,
      description: "This Research Run has no persisted grader execution yet.",
      status: { label: "Not executed" as const, variant: "attention" as const },
    };
  }

  for (const execution of executions) {
    if (
      execution.question_type_id !== run.question_type ||
      execution.question_type_version !== run.question_type_version ||
      execution.workflow_config_version !== run.workflow_config_version ||
      execution.thesis_contract_id !== run.thesis_contract_id
    ) {
      throw new TypeError(
        "Grader Execution is outside Research Run research contract boundary",
      );
    }
    if (
      execution.operator_id !== run.operator_id ||
      execution.research_run_id !== run.id ||
      execution.evidence_bundle_id !== bundle.id ||
      execution.evidence_bundle_hash !== bundle.bundle_hash
    ) {
      throw new TypeError(
        "Grader Execution is outside Research Run or frozen bundle boundary",
      );
    }
  }

  return {
    kind: "ready" as const,
    status: {
      label: `${executions.length} grader execution${executions.length === 1 ? "" : "s"}`,
      variant: "verified" as const,
    },
    executions: executions.map(presentExecution),
  };
}
