export type ReadinessViewRow = {
  operator_id: string;
  research_run_id: string;
  committee_result_id: string;
  committee_memo_id: string;
  canonical_readiness: unknown;
};

export type ResearchRunThesisViewRow = {
  operator_id: string;
  research_run_id: string;
  readiness_gate_result_id: string;
  creation_outcome:
    | "canonical_created"
    | "provisional_created"
    | "no_thesis";
  canonical_creation_result: unknown;
  canonical_thesis: unknown | null;
};

export type ThesisChainViewRow = {
  operator_id: string;
  security_id: string;
  thesis_contract_id: string;
  canonical_chain: unknown;
};

type ReadinessIdentity = {
  operator_id: string;
  security_id: string;
  thesis_contract_id: string;
  research_run_id: string;
  readiness_gate_result_id: string;
  committee_result_id: string;
  committee_memo_id: string;
};

type ThesisIdentity = {
  operator_id: string;
  security_id: string;
  thesis_contract_id: string;
  research_run_id: string;
  readiness_gate_result_id: string;
  thesis_version_id: string;
};

type CreationIdentity = {
  operator_id: string;
  security_id: string;
  thesis_contract_id: string;
  research_run_id: string;
  readiness_gate_result_id: string;
  committee_result_id: string;
  creation_outcome:
    | "canonical_created"
    | "provisional_created"
    | "no_thesis";
  thesis_version_id: string | null;
};

type ChainIdentity<TVersion extends ThesisIdentity> = {
  operator_id: string;
  security_id: string;
  thesis_contract_id: string;
  active_canonical_thesis_version_id: string | null;
  canonical_versions: TVersion[];
  provisional_branches: TVersion[];
};

type FetchReadinessRows = (
  operatorId: string,
  researchRunId: string,
) => Promise<ReadinessViewRow[]>;
type FetchResearchRunThesisRows = (
  operatorId: string,
  researchRunId: string,
) => Promise<ResearchRunThesisViewRow[]>;
type FetchThesisChainRows = (
  operatorId: string,
  securityId: string,
  thesisContractId: string,
) => Promise<ThesisChainViewRow[]>;

function onlyRow<TRow>(rows: TRow[], label: string): TRow | null {
  if (rows.length === 0) return null;
  if (rows.length !== 1) {
    throw new TypeError(`Research Run must have at most one ${label}`);
  }
  return rows[0];
}

export function createReadinessThesisLoader<
  TReadiness extends ReadinessIdentity,
  TCreation extends CreationIdentity,
  TThesis extends ThesisIdentity,
  TChain extends ChainIdentity<TThesis>,
>(
  fetchReadinessRows: FetchReadinessRows,
  fetchResearchRunThesisRows: FetchResearchRunThesisRows,
  fetchThesisChainRows: FetchThesisChainRows,
  parseReadiness: (value: unknown, row: ReadinessViewRow) => TReadiness,
  parseCreation: (
    value: unknown,
    row: ResearchRunThesisViewRow,
    readiness: TReadiness,
    thesis: TThesis | null,
  ) => TCreation,
  parseThesis: (
    value: unknown,
    row: ResearchRunThesisViewRow,
    readiness: TReadiness,
    chain: TChain | null,
  ) => TThesis,
  parseChain: (value: unknown, row: ThesisChainViewRow) => TChain,
) {
  return async function loadReadinessAndThesis(
    operatorId: string,
    researchRunId: string,
    securityId: string,
    thesisContractId: string,
  ) {
    const [readinessRows, thesisRows, chainRows] = await Promise.all([
      fetchReadinessRows(operatorId, researchRunId),
      fetchResearchRunThesisRows(operatorId, researchRunId),
      fetchThesisChainRows(operatorId, securityId, thesisContractId),
    ]);
    const readinessRow = onlyRow(readinessRows, "readiness result");
    const thesisRow = onlyRow(thesisRows, "thesis creation result");
    const chainRow = onlyRow(chainRows, "thesis chain");

    const chain = chainRow === null ? null : parseChain(
      chainRow.canonical_chain,
      chainRow,
    );
    if (chainRow !== null) {
      if (chain === null) {
        throw new TypeError("Thesis chain parser returned no chain");
      }
      if (chainRow.operator_id !== operatorId ||
        chainRow.security_id !== securityId ||
        chainRow.thesis_contract_id !== thesisContractId ||
        chain.operator_id !== operatorId ||
        chain.security_id !== securityId ||
        chain.thesis_contract_id !== thesisContractId) {
        throw new TypeError("Thesis chain is outside requested ownership scope");
      }
    }

    if (readinessRow === null) {
      if (thesisRow !== null) {
        throw new TypeError("Thesis creation exists without readiness result");
      }
      return { readiness: null, creation: null, thesis: null, chain };
    }
    const readiness = parseReadiness(
      readinessRow.canonical_readiness,
      readinessRow,
    );
    if (
      readinessRow.operator_id !== operatorId ||
      readinessRow.research_run_id !== researchRunId ||
      readiness.operator_id !== operatorId ||
      readiness.research_run_id !== researchRunId ||
      readiness.security_id !== securityId ||
      readiness.thesis_contract_id !== thesisContractId ||
      readiness.committee_result_id !== readinessRow.committee_result_id ||
      readiness.committee_memo_id !== readinessRow.committee_memo_id
    ) {
      throw new TypeError(
        "Readiness result is outside requested owner, run, or upstream scope",
      );
    }
    if (thesisRow === null) {
      throw new TypeError("Readiness result is missing thesis creation outcome");
    }
    const thesis = thesisRow.canonical_thesis === null
      ? null
      : parseThesis(thesisRow.canonical_thesis, thesisRow, readiness, chain);
    const creation = parseCreation(
      thesisRow.canonical_creation_result,
      thesisRow,
      readiness,
      thesis,
    );
    const expectsThesis = thesisRow.creation_outcome !== "no_thesis";
    if (
      thesisRow.operator_id !== operatorId ||
      thesisRow.research_run_id !== researchRunId ||
      thesisRow.readiness_gate_result_id !== readiness.readiness_gate_result_id ||
      creation.operator_id !== operatorId ||
      creation.research_run_id !== researchRunId ||
      creation.security_id !== securityId ||
      creation.thesis_contract_id !== thesisContractId ||
      creation.readiness_gate_result_id !== readiness.readiness_gate_result_id ||
      creation.committee_result_id !== readiness.committee_result_id ||
      creation.creation_outcome !== thesisRow.creation_outcome ||
      expectsThesis !== (thesis !== null) ||
      creation.thesis_version_id !== (thesis?.thesis_version_id ?? null) ||
      (thesis !== null &&
        (thesis.operator_id !== operatorId ||
          thesis.research_run_id !== researchRunId ||
          thesis.security_id !== securityId ||
          thesis.thesis_contract_id !== thesisContractId ||
          thesis.readiness_gate_result_id !== readiness.readiness_gate_result_id))
    ) {
      throw new TypeError(
        "Thesis result is outside requested owner, run, readiness, or creation scope",
      );
    }
    if (thesis !== null) {
      const chainMatches = chain === null
        ? []
        : [...chain.canonical_versions, ...chain.provisional_branches].filter(
            (version) => version.thesis_version_id === thesis.thesis_version_id,
          );
      if (chainMatches.length !== 1) {
        throw new TypeError(
          "created thesis does not resolve exactly once in ownership chain",
        );
      }
    }
    return { readiness, creation, thesis, chain };
  };
}
