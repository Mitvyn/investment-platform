import type {
  GraderExecution,
  GraderExecutionValidationContext,
} from "@iros/types";

export type GraderExecutionViewRow = {
  canonical_execution: unknown;
};

type FetchGraderExecutionRows = (
  operatorId: string,
  researchRunId: string,
) => Promise<GraderExecutionViewRow[]>;

type ParseGraderExecution = (
  value: unknown,
  context: GraderExecutionValidationContext,
) => GraderExecution;

export function createGraderExecutionLoader(
  fetchRows: FetchGraderExecutionRows,
  parseExecution: ParseGraderExecution,
) {
  return async function loadGraderExecutions(
    operatorId: string,
    researchRunId: string,
    context: GraderExecutionValidationContext,
  ): Promise<GraderExecution[]> {
    const rows = await fetchRows(operatorId, researchRunId);
    return rows.map((row) => {
      const execution = parseExecution(row.canonical_execution, context);
      if (
        execution.operator_id !== operatorId ||
        execution.research_run_id !== researchRunId
      ) {
        throw new TypeError(
          "Grader Execution is outside requested owner or Research Run scope",
        );
      }
      return execution;
    });
  };
}
