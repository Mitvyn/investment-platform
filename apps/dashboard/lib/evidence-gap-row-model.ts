export type EvidenceGapState = "missing" | "gated";

export function presentEvidenceGap(
  label: string,
  state: EvidenceGapState = "missing",
) {
  return {
    label,
    state,
    stateLabel: state === "gated" ? "Gated" : "Missing",
  } as const;
}
