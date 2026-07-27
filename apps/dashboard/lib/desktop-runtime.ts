type DesktopEnvironment = Record<string, string | undefined>;

export type DesktopRuntimeStatus = {
  detail: string;
  state: "ready" | "failed" | "unavailable";
};

export function readDesktopRuntimeStatus(
  environment: DesktopEnvironment = process.env,
): DesktopRuntimeStatus {
  if (environment.IROS_DESKTOP !== "1") {
    return {
      detail: "Browser session; local worker managed separately",
      state: "unavailable",
    };
  }
  if (environment.IROS_DESKTOP_WORKER_STATE === "ready") {
    return {
      detail: "Worker shell passed startup; job routing pending IRO-047",
      state: "ready",
    };
  }
  return {
    detail: "Local research worker unavailable",
    state: "failed",
  };
}
