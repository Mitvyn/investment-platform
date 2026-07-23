import type { ValuationSnapshot } from "@iros/types";

export type ValuationSnapshotViewRow = {
  canonical_snapshot: unknown;
};

type FetchValuationSnapshotRow = (
  operatorId: string,
  researchRunId: string,
) => Promise<ValuationSnapshotViewRow | null>;

type ParseValuationSnapshot = (value: unknown) => ValuationSnapshot;

export function createValuationSnapshotLoader(
  fetchRow: FetchValuationSnapshotRow,
  parseSnapshot: ParseValuationSnapshot,
) {
  return async function loadValuationSnapshot(
    operatorId: string,
    researchRunId: string,
  ): Promise<ValuationSnapshot | null> {
    const row = await fetchRow(operatorId, researchRunId);
    if (row === null) return null;
    const snapshot = parseSnapshot(row.canonical_snapshot);
    if (
      snapshot.operator_id !== operatorId ||
      snapshot.research_run_id !== researchRunId
    ) {
      throw new TypeError(
        "Valuation Snapshot is outside requested owner or Research Run scope",
      );
    }
    return snapshot;
  };
}
