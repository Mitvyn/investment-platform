export const dashboardSections = [
  "overview",
  "evidence",
  "committee",
  "thesis",
  "audit",
] as const;

export type DashboardSection = (typeof dashboardSections)[number];

const availableDashboardSections = new Set<DashboardSection>([
  "overview",
  "evidence",
]);

export function isDashboardSectionAvailable(section: DashboardSection) {
  return availableDashboardSections.has(section);
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

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

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
      label: titleCase(section),
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
