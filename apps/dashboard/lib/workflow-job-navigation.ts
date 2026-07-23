import type { WorkflowJobReceipt } from "./security-registration.ts";

export type WorkflowJobNavigation =
  | { kind: "refresh" }
  | { kind: "open_security"; href: string }
  | { kind: "pause" }
  | { kind: "stop" };

export function workflowJobNavigation(
  state: WorkflowJobReceipt["state"],
  securityId: string | null,
  pollsCompleted = 0,
  elapsedMilliseconds = 0,
): WorkflowJobNavigation {
  if (state === "completed" && securityId) {
    return {
      kind: "open_security",
      href: `/?security=${encodeURIComponent(securityId)}`,
    };
  }
  if (state === "queued" || state === "running") {
    return {
      kind:
        pollsCompleted >= 40 || elapsedMilliseconds >= 120_000
          ? "pause"
          : "refresh",
    };
  }
  return { kind: "stop" };
}
