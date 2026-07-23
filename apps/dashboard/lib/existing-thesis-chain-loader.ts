export type ExistingThesisChainRow = {
  operator_id: string;
  security_id: string;
  thesis_contract_id: string;
  canonical_chain: unknown;
};

type ChainIdentity = {
  operator_id: string;
  security_id: string;
  thesis_contract_id: string;
};

export function createExistingThesisChainLoader<TChain extends ChainIdentity>(
  fetchRows: (
    operatorId: string,
    securityId: string,
    thesisContractId: string,
  ) => Promise<ExistingThesisChainRow[]>,
  parseChain: (value: unknown, row: ExistingThesisChainRow) => TChain,
) {
  return async function loadExistingThesisChain(
    operatorId: string,
    securityId: string,
    thesisContractId: string,
  ) {
    const rows = await fetchRows(operatorId, securityId, thesisContractId);
    if (rows.length === 0) return null;
    if (rows.length !== 1) {
      throw new TypeError("Ownership tuple must have at most one thesis chain");
    }
    const row = rows[0];
    const chain = parseChain(row.canonical_chain, row);
    if (
      row.operator_id !== operatorId ||
      row.security_id !== securityId ||
      row.thesis_contract_id !== thesisContractId ||
      chain.operator_id !== operatorId ||
      chain.security_id !== securityId ||
      chain.thesis_contract_id !== thesisContractId
    ) {
      throw new TypeError("Thesis chain is outside requested ownership scope");
    }
    return chain;
  };
}
