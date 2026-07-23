import {
  parseEvidenceBundle,
  type EvidenceBundle,
} from "../../../packages/types/evidence-bundle.ts";

type EvidenceBundleViewRow = {
  canonical_bundle: unknown;
};

type FetchEvidenceBundleRow = (
  operatorId: string,
  researchRunId: string,
) => Promise<EvidenceBundleViewRow | null>;

export function createEvidenceBundleLoader(fetchRow: FetchEvidenceBundleRow) {
  return async function loadEvidenceBundle(
    operatorId: string,
    researchRunId: string,
  ): Promise<EvidenceBundle | null> {
    const row = await fetchRow(operatorId, researchRunId);
    if (row === null) return null;
    const bundle = parseEvidenceBundle(row.canonical_bundle);
    if (
      bundle.operator_id !== operatorId ||
      bundle.research_run_id !== researchRunId
    ) {
      throw new TypeError(
        "Evidence Bundle is outside requested owner or Research Run scope",
      );
    }
    return bundle;
  };
}

async function fetchEvidenceBundleRow(
  operatorId: string,
  researchRunId: string,
): Promise<EvidenceBundleViewRow | null> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_research_run_evidence_bundle")
    .select("operator_id,research_run_id,canonical_bundle")
    .eq("operator_id", operatorId)
    .eq("research_run_id", researchRunId)
    .maybeSingle();

  if (error) {
    throw new Error(`Evidence Bundle API failed: ${error.message}`);
  }
  if (data === null) return null;
  return { canonical_bundle: data.canonical_bundle };
}

export const loadEvidenceBundle = createEvidenceBundleLoader(
  fetchEvidenceBundleRow,
);
