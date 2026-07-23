import {
  MVP_COMMITTEE_ROSTER,
  type CommitteeGraderId,
  type CommitteeState,
  type CommitteeStatus,
} from "../../../packages/types/committee.ts";

type StateVariant = "verified" | "attention" | "destructive" | "secondary";
type GraderState =
  | "accepted"
  | "abstained"
  | "failed"
  | "not_eligible"
  | "not_executed";
type Stance = "supports" | "mixed" | "challenges";

type ExecutionShape = {
  grader_id?: unknown;
  grader_version?: unknown;
  execution_state?: unknown;
  opinion?: unknown;
  not_eligible?: unknown;
  not_executed?: unknown;
  failure?: unknown;
};

const GRADER_LABELS: Record<CommitteeGraderId, string> = {
  moonshot: "Moonshot",
  catalyst: "Catalyst",
  biotech: "Biotech",
  risk_dilution: "Risk / Dilution",
  valuation: "Valuation",
};

const GRADER_ROSTER = MVP_COMMITTEE_ROSTER.map((grader) => ({
  graderId: grader.grader_id,
  label: GRADER_LABELS[grader.grader_id],
  ownedQuestion: grader.owned_decision_question,
}));

const SHARED_PROPOSITION = {
  id: "biotech_moonshot_catalyst_case",
  version: "biotech_moonshot_catalyst_case.v1",
  text: "As of the cutoff, the available evidence supports a credible Moonshot research case with an identifiable catalyst capable of materially resolving uncertainty.",
} as const;

const NOT_EXECUTED = {
  label: "Not executed" as const,
  variant: "attention" as StateVariant,
};

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function statePresentation(state: GraderState) {
  switch (state) {
    case "accepted":
      return { label: "Accepted" as const, variant: "verified" as const };
    case "abstained":
      return { label: "Abstained" as const, variant: "attention" as const };
    case "failed":
      return { label: "Failed" as const, variant: "destructive" as const };
    case "not_eligible":
      return { label: "Not eligible" as const, variant: "secondary" as const };
    default:
      return NOT_EXECUTED;
  }
}

function normalizeState(value: unknown): GraderState {
  if (
    value === "accepted" ||
    value === "abstained" ||
    value === "failed" ||
    value === "not_eligible"
  ) {
    return value;
  }
  return "not_executed";
}

function acceptedStance(execution: ExecutionShape): Stance | null {
  if (execution.execution_state !== "accepted") return null;
  const opinion = record(execution.opinion);
  const stance = opinion?.stance;
  if (stance === "supports" || stance === "mixed" || stance === "challenges") {
    return stance;
  }
  return null;
}

function stancePresentation(stance: Stance | null) {
  if (stance === "supports") {
    return { label: "Supports" as const, variant: "verified" as const };
  }
  if (stance === "mixed") {
    return { label: "Mixed" as const, variant: "attention" as const };
  }
  if (stance === "challenges") {
    return { label: "Challenges" as const, variant: "destructive" as const };
  }
  return null;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function stringArray(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.length > 0)
    : [];
}

function opinionDetails(execution: ExecutionShape | undefined, state: GraderState) {
  const opinion = record(execution?.opinion);
  const claims = Array.isArray(opinion?.material_claims)
    ? opinion.material_claims.map(record).filter((item) => item !== null)
    : [];
  const gaps = Array.isArray(opinion?.evidence_gaps)
    ? opinion.evidence_gaps.map(record).filter((item) => item !== null)
    : [];
  const abstention = record(opinion?.abstention);
  const proposition = record(opinion?.proposition);
  const failure = record(execution?.failure);
  const notEligible = record(execution?.not_eligible);
  const notExecuted = record(execution?.not_executed);

  const citations = [
    ...new Set(
      claims.flatMap((claim) => stringArray(claim.evidence_ids)),
    ),
  ].sort();
  const materialClaims = claims
    .map((claim) => {
      const text = stringValue(claim.claim);
      if (text === null) return null;
      return {
        claim: text,
        evidenceIds: stringArray(claim.evidence_ids),
      };
    })
    .filter((claim): claim is { claim: string; evidenceIds: string[] } => claim !== null);
  const evidenceGaps = gaps
    .map((gap) => {
      const description = stringValue(gap.description);
      const required = stringValue(gap.required_evidence);
      if (description && required) return `${description} Required: ${required}`;
      return description ?? required;
    })
    .filter((gap): gap is string => gap !== null);

  let reason = stringValue(proposition?.stance_rationale);
  if (state === "abstained") {
    reason = stringValue(abstention?.reason) ?? stringValue(opinion?.summary);
    evidenceGaps.push(...stringArray(abstention?.evidence_required));
  } else if (state === "failed") {
    reason = stringValue(failure?.final_reason);
  } else if (state === "not_eligible") {
    reason =
      stringValue(notEligible?.reason) ??
      stringValue(notEligible?.human_readable_reason);
  } else if (state === "not_executed") {
    reason = stringValue(notExecuted?.reason) ?? "No persisted grader result.";
  }

  return {
    opinionId: stringValue(opinion?.opinion_id),
    version: stringValue(execution?.grader_version),
    confidence: stringValue(opinion?.confidence),
    summary: stringValue(opinion?.summary),
    reason,
    claims: materialClaims,
    citations,
    gaps: [...new Set(evidenceGaps)],
  };
}

function committeeStatusPresentation(code: CommitteeStatus) {
  if (code === "incomplete_required_grader_failed") {
    return {
      code: "incomplete_required_grader_failed" as const,
      label: "Required grader failed" as const,
      variant: "destructive" as const,
    };
  }
  if (code === "insufficient_accepted_opinions") {
    return {
      code: "insufficient_accepted_opinions" as const,
      label: "Insufficient accepted opinions" as const,
      variant: "attention" as const,
    };
  }
  if (code === "complete_with_abstentions") {
    return {
      code: "complete_with_abstentions" as const,
      label: "Complete with abstentions" as const,
      variant: "attention" as const,
    };
  }
  return {
    code: "complete" as const,
    label: "Complete" as const,
    variant: "verified" as const,
  };
}

function deriveDisplayStatus(states: GraderState[]): CommitteeStatus {
  if (states.includes("failed")) return "incomplete_required_grader_failed";
  const eligibleCount = states.filter((state) => state !== "not_eligible").length;
  if (eligibleCount === 0 || states.includes("not_executed")) {
    return "insufficient_accepted_opinions";
  }
  if (states.includes("abstained")) return "complete_with_abstentions";
  return states.filter((state) => state === "accepted").length === eligibleCount
    ? "complete"
    : "insufficient_accepted_opinions";
}

export function presentGraderCommitteeWorkspace(
  source: CommitteeState | readonly unknown[] | null,
) {
  const committee =
    source !== null && !Array.isArray(source) ? (source as CommitteeState) : null;
  const executions: readonly unknown[] = committee
    ? committee.grader_results
    : source === null
      ? []
      : (source as readonly unknown[]);
  const byGrader = new Map<string, ExecutionShape>();
  for (const candidate of executions) {
    const execution = record(candidate) as ExecutionShape | null;
    if (typeof execution?.grader_id === "string") {
      byGrader.set(execution.grader_id, execution);
    }
  }
  const normalized = GRADER_ROSTER.map((grader) => {
    const execution = byGrader.get(grader.graderId);
    const state = normalizeState(execution?.execution_state);
    return { grader, execution, state, stance: execution ? acceptedStance(execution) : null };
  });
  const states = normalized.map((item) => item.state);
  const acceptedStances = normalized
    .map((item) => item.stance)
    .filter((stance): stance is Stance => stance !== null);

  const counts = committee
    ? {
        accepted: committee.accounting.accepted_count,
        abstained: committee.accounting.abstained_count,
        eligible: committee.accounting.eligible_count,
        notEligible: committee.accounting.not_eligible_count,
        failed: committee.accounting.failed_count,
        notExecuted: committee.accounting.not_executed_count,
      }
    : {
        accepted: states.filter((state) => state === "accepted").length,
        abstained: states.filter((state) => state === "abstained").length,
        eligible: states.filter((state) => state !== "not_eligible").length,
        notEligible: states.filter((state) => state === "not_eligible").length,
        failed: states.filter((state) => state === "failed").length,
        notExecuted: states.filter((state) => state === "not_executed").length,
      };
  const agreement = committee
    ? {
        supports: committee.stance_counts.supports,
        mixed: committee.stance_counts.mixed,
        challenges: committee.stance_counts.challenges,
        denominator: committee.accounting.accepted_count,
      }
    : {
        supports: acceptedStances.filter((stance) => stance === "supports").length,
        mixed: acceptedStances.filter((stance) => stance === "mixed").length,
        challenges: acceptedStances.filter((stance) => stance === "challenges").length,
        denominator: acceptedStances.length,
      };

  return {
    proposition: committee
      ? {
          id: committee.proposition_id,
          version: committee.proposition_version,
          text: committee.rendered_proposition_text,
        }
      : SHARED_PROPOSITION,
    status: committeeStatusPresentation(
      committee?.committee_status ?? deriveDisplayStatus(states),
    ),
    counts,
    agreement,
    rows: normalized.map(({ grader, execution, state, stance }) => ({
      ...grader,
      stateCode: state,
      state: statePresentation(state),
      stance: stancePresentation(stance),
      ...opinionDetails(execution, state),
    })),
  };
}
