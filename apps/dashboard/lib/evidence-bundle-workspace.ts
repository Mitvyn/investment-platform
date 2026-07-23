import type { EvidenceBundle } from "../../../packages/types/evidence-bundle.ts";
import type { ResearchRun } from "../../../packages/types/research-run.ts";

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function filingPeriod(start: string | null, end: string | null) {
  if (start !== null && end !== null) return `${start} to ${end}`;
  return start ?? end ?? "Not applicable";
}

export function presentEvidenceBundleWorkspace(
  run: ResearchRun,
  bundle: EvidenceBundle | null,
) {
  if (bundle === null) {
    return {
      kind: "missing" as const,
      description:
        "This eligible Research Run has no persisted Evidence Bundle yet.",
      status: { label: "Not materialized" as const, variant: "attention" as const },
    };
  }
  if (
    bundle.operator_id !== run.operator_id ||
    bundle.research_run_id !== run.id ||
    bundle.security_id !== run.security_id ||
    bundle.as_of_cutoff !== run.as_of_cutoff
  ) {
    throw new TypeError("Evidence Bundle does not match Research Run boundary");
  }

  return {
    kind: "ready" as const,
    bundle,
    status: { label: "Frozen" as const, variant: "verified" as const },
    readiness: bundle.grader_ready
      ? {
          label: "Grader ready" as const,
          variant: "verified" as const,
          description: "Blocking primary evidence requirements are satisfied.",
        }
      : {
          label: "Blocked" as const,
          variant: "destructive" as const,
          description: "Blocking primary evidence requirements remain unresolved.",
        },
    summary: [
      { label: "Bundle ID", value: bundle.id },
      { label: "Bundle hash", value: bundle.bundle_hash },
      { label: "Cutoff", value: bundle.as_of_cutoff },
      { label: "Manifest items", value: String(bundle.manifest.length) },
      { label: "Evidence policy", value: bundle.evidence_policy_version },
      { label: "Freshness policy", value: bundle.freshness_policy_version },
      { label: "Frozen", value: bundle.created_at },
    ],
    gaps: bundle.gaps.map((gap) => ({
      id: gap.gap_id,
      requirement: gap.requirement_id,
      sourceClass: titleCase(gap.source_class),
      reason: gap.reason_code,
      explanation: gap.explanation,
    })),
    manifest: bundle.manifest.map((item) => ({
      ordinal: String(item.ordinal).padStart(2, "0"),
      sourceClass:
        item.source_class === "sec" ? "SEC" : titleCase(item.source_class),
      itemKind: titleCase(item.item_kind),
      sourceUrl: item.source_locator,
      freshness: {
        label: titleCase(item.freshness_state),
        variant:
          item.freshness_state === "current"
            ? ("verified" as const)
            : ("attention" as const),
      },
      fields: [
        { label: "Item ID", value: item.item_id },
        { label: "Item version", value: item.item_version_id },
        { label: "Locator", value: item.locator },
        { label: "Content SHA-256", value: item.content_sha256 },
        { label: "Published", value: item.published_at ?? "Not available" },
        { label: "Retrieved", value: item.retrieved_at },
        { label: "Effective", value: item.effective_at ?? "Not applicable" },
        {
          label: "Filing period",
          value: filingPeriod(item.filing_period_start, item.filing_period_end),
        },
        { label: "Freshness reason", value: item.freshness_reason_code },
        { label: "Freshness policy", value: item.freshness_policy_version },
      ],
    })),
  };
}
