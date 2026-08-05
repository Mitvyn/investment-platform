import { parseResearchValuationSnapshot } from "@iros/types";

import {
  createValuationSnapshotLoader,
  type ValuationSnapshotViewRow,
} from "./valuation-snapshot-loader.ts";

async function fetchValuationSnapshotRow(
  operatorId: string,
  researchRunId: string,
): Promise<ValuationSnapshotViewRow | null> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_research_run_valuation_snapshot")
    .select(
      "operator_id,research_run_id,evidence_bundle_id,valuation_snapshot_id,snapshot_status,price_information_state,canonical_snapshot",
    )
    .eq("operator_id", operatorId)
    .eq("research_run_id", researchRunId)
    .maybeSingle();

  if (error) {
    throw new Error(`Valuation Snapshot API failed: ${error.message}`);
  }
  if (data === null) return null;
  return { canonical_snapshot: data.canonical_snapshot };
}

export const loadValuationSnapshot = createValuationSnapshotLoader(
  fetchValuationSnapshotRow,
  parseResearchValuationSnapshot,
);
