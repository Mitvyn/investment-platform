import type { ResearchRunCommandState } from "../../../packages/types/research-run-command.ts";

const MAX_POLL_COUNT = 40;
const MAX_POLL_DURATION_MS = 120_000;

export type ResearchRunCommandNavigation =
  | { kind: "refresh" }
  | { kind: "open_research_run"; href: string }
  | { kind: "pause" }
  | { kind: "stop" };

export function researchRunCommandNavigation(
  state: ResearchRunCommandState,
  researchRunId: string | null,
  pollsCompleted = 0,
  elapsedMilliseconds = 0,
  contractVersion:
    | "research_run_command_receipt.v1"
    | "research_run_command_receipt.v2" = "research_run_command_receipt.v2",
): ResearchRunCommandNavigation {
  if (contractVersion === "research_run_command_receipt.v1") {
    return { kind: "stop" };
  }
  if (state === "completed" && researchRunId) {
    return {
      kind: "open_research_run",
      href: `/research-runs/${researchRunId}`,
    };
  }
  if (state !== "queued" && state !== "running") return { kind: "stop" };
  if (
    pollsCompleted >= MAX_POLL_COUNT ||
    elapsedMilliseconds >= MAX_POLL_DURATION_MS
  ) {
    return { kind: "pause" };
  }
  return { kind: "refresh" };
}
