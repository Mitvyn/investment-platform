import type {
  ResearchRunHistory,
  ResearchRunHistoryItem,
} from "./research-run-history-loader.ts";

type StateBadge = {
  label: string;
  variant: "verified" | "attention" | "destructive" | "outline";
};

function sentenceCase(value: string) {
  const normalized = value.replaceAll("_", " ");
  return `${normalized.slice(0, 1).toUpperCase()}${normalized.slice(1)}`;
}

function presentItem(
  item: ResearchRunHistoryItem,
  isLatest: boolean,
) {
  const { run, readiness } = item;
  let workflowState: StateBadge;
  if (!run.eligibility.eligible) {
    workflowState = { label: "Not eligible", variant: "destructive" };
  } else if (readiness === null) {
    workflowState = {
      label: "Readiness result unavailable",
      variant: "attention",
    };
  } else {
    workflowState = {
      label: `Readiness ${sentenceCase(readiness.readinessStatus).toLowerCase()}`,
      variant:
        readiness.readinessStatus === "passed"
          ? "verified"
          : readiness.readinessStatus === "blocked"
            ? "attention"
            : "outline",
    };
  }
  return {
    runId: run.id,
    auditHref: `/research-runs/${run.id}`,
    cutoff: run.as_of_cutoff,
    createdAt: run.created_at,
    eligibility: {
      label: run.eligibility.eligible ? "Eligible" : "Not eligible",
      variant: run.eligibility.eligible
        ? ("verified" as const)
        : ("destructive" as const),
    },
    workflowState,
    requestedDisposition:
      readiness === null
        ? "Not produced"
        : sentenceCase(readiness.requestedDisposition),
    finalDisposition:
      readiness === null
        ? "Not produced"
        : sentenceCase(readiness.finalDisposition),
    committeeStatus:
      readiness === null
        ? "Not produced"
        : sentenceCase(readiness.committeeStatus),
    evaluatedAt: readiness?.evaluatedAt ?? null,
    isLatest,
  };
}

export function presentResearchRunHistory(history: ResearchRunHistory) {
  if (history.items.length === 0) {
    return {
      kind: "empty" as const,
      title: "No finalized Research Runs",
      description:
        "No complete eligibility snapshot exists for this stable security.",
      items: [],
    };
  }
  const items = history.items.map((item, index) =>
    presentItem(item, index === 0),
  );
  return {
    kind: "ready" as const,
    latest: items[0],
    items,
  };
}

export type ResearchRunHistoryPresentation = ReturnType<
  typeof presentResearchRunHistory
>;
