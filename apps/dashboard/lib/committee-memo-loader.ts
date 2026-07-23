export type CommitteeMemoViewRow = {
  operator_id: string;
  research_run_id: string;
  committee_result_id: string;
  canonical_memo: unknown;
};

type CommitteeMemoIdentity = {
  research_run_id: string;
  committee_id: string;
};

type FetchCommitteeMemoRows = (
  operatorId: string,
  researchRunId: string,
) => Promise<CommitteeMemoViewRow[]>;

type ParseCommitteeMemo<TMemo extends CommitteeMemoIdentity> = (
  value: unknown,
  row: CommitteeMemoViewRow,
) => TMemo;

export function createCommitteeMemoLoader<
  TMemo extends CommitteeMemoIdentity,
>(
  fetchRows: FetchCommitteeMemoRows,
  parseMemo: ParseCommitteeMemo<TMemo>,
) {
  return async function loadCommitteeMemo(
    operatorId: string,
    researchRunId: string,
  ): Promise<TMemo | null> {
    const rows = await fetchRows(operatorId, researchRunId);
    if (rows.length === 0) return null;
    if (rows.length !== 1) {
      throw new TypeError("Research Run must have exactly one canonical memo");
    }

    const row = rows[0];
    const memo = parseMemo(row.canonical_memo, row);
    if (
      row.operator_id !== operatorId ||
      row.research_run_id !== researchRunId ||
      memo.research_run_id !== researchRunId ||
      memo.committee_id !== row.committee_result_id
    ) {
      throw new TypeError(
        "Committee memo is outside requested owner, Research Run, or committee scope",
      );
    }
    return memo;
  };
}
