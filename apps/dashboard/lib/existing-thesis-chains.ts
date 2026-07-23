import { parseThesisChain, type ThesisChain } from "@iros/types";

import {
  createExistingThesisChainLoader,
  type ExistingThesisChainRow,
} from "./existing-thesis-chain-loader.ts";

async function fetchRows(
  operatorId: string,
  securityId: string,
  thesisContractId: string,
): Promise<ExistingThesisChainRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_thesis_chains")
    .select("operator_id,security_id,thesis_contract_id,canonical_chain")
    .eq("operator_id", operatorId)
    .eq("security_id", securityId)
    .eq("thesis_contract_id", thesisContractId)
    .limit(2);
  if (error) throw new Error(`Thesis Chain API failed: ${error.message}`);
  return (data ?? []) as unknown as ExistingThesisChainRow[];
}

export const loadExistingThesisChain = createExistingThesisChainLoader<ThesisChain>(
  fetchRows,
  (value, row) => parseThesisChain(value, {
    operatorId: row.operator_id,
    securityId: row.security_id,
    thesisContractId: row.thesis_contract_id,
  }),
);
