/**
 * Top-level product features. Three features plus a low-priority Settings item.
 *
 * Dashboard is the daily command centre: funds, holdings, broker state, market
 * movement, watchlist. Research is one ticker-selectable, run-centred flow.
 * Quant is deliberately isolated so its datasets and signals can never reach
 * evidence, readiness, or thesis logic (architecture decision 0001).
 */
export const dashboardSections = [
  "dashboard",
  "research",
  "quant",
  "settings",
] as const;

export type DashboardSection = (typeof dashboardSections)[number];

export const dashboardSectionLabels: Record<DashboardSection, string> = {
  dashboard: "Dashboard",
  research: "Research",
  quant: "Quant",
  settings: "Settings",
};

/** Features shown in the primary rail. Settings sits apart, near sign-out. */
export const primaryDashboardSections = [
  "dashboard",
  "research",
  "quant",
] as const;

const availableDashboardSections = new Set<DashboardSection>([
  "dashboard",
  "research",
  "settings",
]);

export function isDashboardSectionAvailable(section: DashboardSection) {
  return availableDashboardSections.has(section);
}

export function parseDashboardSection(
  value: string | undefined,
): DashboardSection {
  return dashboardSections.includes(value as DashboardSection)
    ? (value as DashboardSection)
    : "dashboard";
}

/**
 * Stages of one Research Run, in chain order. These are stages inside a single
 * feature, not global navigation: the operator picks a security once and the
 * whole workspace follows that run from eligibility to operator decision.
 */
export const researchStages = [
  "overview",
  "evidence",
  "valuation",
  "opinions",
  "committee",
  "thesis",
] as const;

export type ResearchStage = (typeof researchStages)[number];

export const researchStageLabels: Record<ResearchStage, string> = {
  overview: "Overview",
  evidence: "Evidence",
  valuation: "Valuation",
  opinions: "Opinions",
  committee: "Committee",
  thesis: "Thesis",
};

export function parseResearchStage(value: string | undefined): ResearchStage {
  return researchStages.includes(value as ResearchStage)
    ? (value as ResearchStage)
    : "overview";
}

export type ResearchRunFacts = {
  hasSecurity: boolean;
  hasEvidenceTrace: boolean;
  hasValuationContext: boolean;
  hasFinalizedRun: boolean;
  hasCommitteeReconciliation: boolean;
  hasReadiness: boolean;
  latestRunId: string | null;
};

export type ResearchStageState = {
  id: ResearchStage;
  label: string;
  available: boolean;
  /** Why this stage has no artifact yet. Null when available. */
  blockedReason: string | null;
  /** The single next thing that would unblock it. Null when available. */
  nextStep: string | null;
  /** Set when the stage's artifact lives on the run route. */
  runHref: string | null;
};

/**
 * Resolves every stage's availability from persisted artifacts.
 *
 * A stage is never silently empty. When no artifact exists it states exactly
 * what is missing and what would produce it, because an operator looking at a
 * blank Committee stage otherwise cannot tell a broken pipeline from a run
 * that simply has not reached that point.
 */
export function presentResearchStages(
  facts: ResearchRunFacts,
): ResearchStageState[] {
  const runHref = facts.latestRunId
    ? `/research-runs/${facts.latestRunId}`
    : null;

  const noSecurity = {
    blockedReason: "No security is selected.",
    nextStep: "Choose a registered security to begin a Research Run.",
  };

  const definitions: Array<{
    id: ResearchStage;
    available: boolean;
    blockedReason: string;
    nextStep: string;
    href?: string | null;
  }> = [
    {
      id: "overview",
      available: facts.hasSecurity,
      blockedReason: noSecurity.blockedReason,
      nextStep: noSecurity.nextStep,
    },
    {
      id: "evidence",
      available: facts.hasSecurity && facts.hasEvidenceTrace,
      blockedReason: "No frozen evidence bundle exists for this security.",
      nextStep:
        "Run preflight from Overview to collect and freeze primary sources.",
    },
    {
      id: "valuation",
      available: facts.hasSecurity && facts.hasValuationContext,
      blockedReason: "No valuation snapshot or market context is stored.",
      nextStep:
        "Collect market context and issuer financials, then run preflight.",
    },
    {
      id: "opinions",
      available: facts.hasSecurity && facts.hasFinalizedRun,
      blockedReason: "No finalized Research Run has produced grader opinions.",
      nextStep: "Launch a Research Committee run from Overview.",
      href: runHref,
    },
    {
      id: "committee",
      available: facts.hasSecurity && facts.hasCommitteeReconciliation,
      blockedReason: "No committee reconciliation exists for this security.",
      nextStep:
        "Five independent opinions must complete before reconciliation runs.",
      href: runHref,
    },
    {
      id: "thesis",
      available: facts.hasSecurity && facts.hasReadiness,
      blockedReason: "No readiness evaluation or thesis has been produced.",
      nextStep:
        "Committee reconciliation must pass the readiness gate before a thesis exists.",
      href: runHref,
    },
  ];

  return definitions.map((definition) => ({
    id: definition.id,
    label: researchStageLabels[definition.id],
    available: definition.available,
    blockedReason: definition.available
      ? null
      : facts.hasSecurity
        ? definition.blockedReason
        : noSecurity.blockedReason,
    nextStep: definition.available
      ? null
      : facts.hasSecurity
        ? definition.nextStep
        : noSecurity.nextStep,
    runHref: definition.available ? (definition.href ?? null) : null,
  }));
}

/** The furthest stage that has a persisted artifact. Always at least Overview. */
export function furthestAvailableStage(
  stages: ResearchStageState[],
): ResearchStage {
  const available = stages.filter((stage) => stage.available);
  return available.length > 0
    ? available[available.length - 1].id
    : "overview";
}

export type PriceInformationState =
  | "aligned"
  | "pre_material_evidence"
  | "indeterminate";

type DashboardShellInput = {
  activeSection: DashboardSection;
  evidenceBundleHash: string;
  evidenceCutoff: string;
  marketPriceSession: string;
  priceInformationState: PriceInformationState;
};

const statePresentation: Record<
  PriceInformationState,
  { label: string; tone: "verified" | "attention" | "indeterminate" }
> = {
  aligned: { label: "Aligned", tone: "verified" },
  pre_material_evidence: { label: "Price predates evidence", tone: "attention" },
  indeterminate: { label: "Indeterminate", tone: "indeterminate" },
};

function formatUtcTimestamp(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    hour: "2-digit",
    hour12: false,
    minute: "2-digit",
    month: "short",
    timeZone: "UTC",
    timeZoneName: "short",
    year: "numeric",
  }).format(new Date(value));
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
    year: "numeric",
  }).format(new Date(`${value}T00:00:00Z`));
}

export function presentDashboardShell(input: DashboardShellInput) {
  const presentation = statePresentation[input.priceInformationState];
  return {
    navigation: dashboardSections.map((section) => ({
      available: isDashboardSectionAvailable(section),
      current: section === input.activeSection,
      id: section,
      label: dashboardSectionLabels[section],
    })),
    informationAlignment: {
      fields: [
        { label: "Evidence cutoff", value: formatUtcTimestamp(input.evidenceCutoff) },
        { label: "Market price session", value: formatDate(input.marketPriceSession) },
        { label: "Evidence bundle", value: input.evidenceBundleHash },
      ],
      label: "Information alignment",
      state: {
        ...presentation,
        value: input.priceInformationState,
      },
    },
  };
}
