export type StatusStripInput = {
  moomooState: string;
  portfolioState: string;
  runtimeState: "ready" | "failed" | "unavailable";
  sourceCount: number;
  sourceTotal: number;
  marketReady: boolean;
};

export function presentStatusStrip(input: StatusStripInput) {
  return [
    {
      label: "Evidence",
      value: `${input.sourceCount}/${input.sourceTotal}`,
      tone: input.sourceCount === input.sourceTotal ? "verified" : "attention",
    },
    {
      label: "Market",
      value: input.marketReady ? "Ready" : "Unavailable",
      tone: input.marketReady ? "verified" : "attention",
    },
    {
      label: "Runtime",
      value: input.runtimeState === "ready" ? "Ready" : "Offline",
      tone: input.runtimeState === "ready" ? "verified" : "attention",
    },
    {
      label: "Portfolio",
      value: input.portfolioState,
      tone: input.portfolioState === "Synced" ? "verified" : "attention",
    },
    {
      label: "Moomoo",
      value: input.moomooState,
      tone: input.moomooState === "connected" ? "verified" : "attention",
    },
  ] as const;
}
