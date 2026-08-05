import {
  RESEARCH_COMMAND_STAGES,
  type ResearchRunCommandProgress,
  type ResearchRunCommandStage,
} from "./research-run-command-progress-loader.ts";

type ProgressBadge = {
  label: string;
  variant: "verified" | "attention" | "destructive" | "outline";
};

function stageLabel(stage: ResearchRunCommandStage) {
  const value = stage.replaceAll("_", " ");
  return `${value.slice(0, 1).toUpperCase()}${value.slice(1)}`;
}

function commandStatus(
  state: ResearchRunCommandProgress["command_state"],
): ProgressBadge {
  switch (state) {
    case "blocked":
      return { label: "Launch blocked", variant: "attention" };
    case "queued":
      return { label: "Queued", variant: "outline" };
    case "running":
      return { label: "Running", variant: "attention" };
    case "completed":
      return { label: "Completed", variant: "verified" };
    case "failed":
      return { label: "Failed", variant: "destructive" };
  }
}

export function presentResearchRunCommandProgress(
  progress: ResearchRunCommandProgress,
  now: Date,
) {
  if (Number.isNaN(now.getTime())) {
    throw new TypeError("current time is invalid");
  }
  const leaseExpired =
    progress.command_state === "running" &&
    progress.lease_expires_at !== null &&
    now.getTime() >= Date.parse(progress.lease_expires_at);
  const lease: ProgressBadge & { expiresAt: string | null } =
    progress.command_state !== "running"
      ? {
          label: "Lease not active",
          variant: "outline",
          expiresAt: progress.lease_expires_at,
        }
      : leaseExpired
        ? {
            label: "Lease expired",
            variant: "destructive",
            expiresAt: progress.lease_expires_at,
          }
        : {
            label: "Lease fresh",
            variant: "verified",
            expiresAt: progress.lease_expires_at,
          };
  return {
    commandId: progress.command_id,
    state: progress.command_state,
    status: commandStatus(progress.command_state),
    attempt:
      progress.attempt_number === null
        ? "No attempt"
        : `Attempt ${progress.attempt_number} of 2`,
    activeStage:
      progress.active_stage === null
        ? "No active stage"
        : stageLabel(progress.active_stage),
    completedStages: progress.completed_stages.map((stage) => ({
      ordinal: RESEARCH_COMMAND_STAGES.indexOf(stage) + 1,
      stage,
      label: stageLabel(stage),
    })),
    lease,
    failure:
      progress.command_state === "failed" &&
      progress.failure_stage !== null &&
      progress.error_code !== null
        ? {
            stage: stageLabel(progress.failure_stage),
            errorCode: progress.error_code,
            retryable: progress.retryable === true,
          }
        : null,
    updatedAt: progress.updated_at,
  };
}

export type ResearchRunCommandProgressPresentation = ReturnType<
  typeof presentResearchRunCommandProgress
>;
