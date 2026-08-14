import assert from "node:assert/strict";
import test from "node:test";

import { presentStatusStrip } from "./status-strip-model.ts";

test("status strip compresses readiness into five glanceable states", () => {
  assert.deepEqual(
    presentStatusStrip({
      marketReady: true,
      moomooState: "connected",
      portfolioState: "Synced",
      runtimeState: "ready",
      sourceCount: 2,
      sourceTotal: 2,
    }),
    [
      { label: "Evidence", value: "2/2", tone: "verified" },
      { label: "Market", value: "Ready", tone: "verified" },
      { label: "Runtime", value: "Ready", tone: "verified" },
      { label: "Portfolio", value: "Synced", tone: "verified" },
      { label: "Moomoo", value: "connected", tone: "verified" },
    ],
  );
});
