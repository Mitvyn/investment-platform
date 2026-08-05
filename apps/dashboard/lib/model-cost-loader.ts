export type ModelCostScopedRow = {
  operator_id: string;
  research_run_id: string;
  [key: string]: unknown;
};

export type ModelCostBudgetRow = ModelCostScopedRow;
export type ModelCostReservationRow = ModelCostScopedRow;
export type ModelCostAttemptRow = ModelCostScopedRow;

type FetchRows<TRow extends ModelCostScopedRow> = (
  operatorId: string,
  researchRunId: string,
) => Promise<TRow[]>;

function assertScope(
  rows: ModelCostScopedRow[],
  operatorId: string,
  researchRunId: string,
) {
  if (
    rows.some(
      (row) =>
        row.operator_id !== operatorId ||
        row.research_run_id !== researchRunId,
    )
  ) {
    throw new TypeError(
      "Model accounting row is outside requested owner or Research Run scope",
    );
  }
}

export function createModelCostLoader(
  fetchBudgetRows: FetchRows<ModelCostBudgetRow>,
  fetchReservationRows: FetchRows<ModelCostReservationRow>,
  fetchAttemptRows: FetchRows<ModelCostAttemptRow>,
) {
  return async function loadModelCosts(
    operatorId: string,
    researchRunId: string,
  ) {
    const [budgets, reservations, attempts] = await Promise.all([
      fetchBudgetRows(operatorId, researchRunId),
      fetchReservationRows(operatorId, researchRunId),
      fetchAttemptRows(operatorId, researchRunId),
    ]);
    assertScope(budgets, operatorId, researchRunId);
    assertScope(reservations, operatorId, researchRunId);
    assertScope(attempts, operatorId, researchRunId);
    return { budgets, reservations, attempts };
  };
}

export type ModelCostData = Awaited<
  ReturnType<ReturnType<typeof createModelCostLoader>>
>;
