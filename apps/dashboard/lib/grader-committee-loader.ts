import type { CommitteeState } from "@iros/types";

export type GraderCommitteeViewRow = {
  operator_id: string;
  research_run_id: string;
  canonical_committee: unknown;
};

type FetchGraderCommitteeRows = (
  operatorId: string,
  researchRunId: string,
) => Promise<GraderCommitteeViewRow[]>;

type ParseCommittee = (value: unknown) => CommitteeState;

export function createGraderCommitteeLoader(
  fetchRows: FetchGraderCommitteeRows,
  parseCommittee: ParseCommittee,
) {
  return async function loadGraderCommittee(
    operatorId: string,
    researchRunId: string,
  ): Promise<CommitteeState | null> {
    const rows = await fetchRows(operatorId, researchRunId);
    if (rows.length === 0) return null;
    if (rows.length !== 1) {
      throw new TypeError("Research Run must have exactly one canonical committee");
    }

    const row = rows[0];
    if (
      row.operator_id !== operatorId ||
      row.research_run_id !== researchRunId
    ) {
      throw new TypeError(
        "Committee is outside requested owner or Research Run scope",
      );
    }
    const committee = parseCommittee(row.canonical_committee);
    if (committee.research_run_id !== researchRunId) {
      throw new TypeError(
        "Committee is outside requested owner or Research Run scope",
      );
    }
    return committee;
  };
}
