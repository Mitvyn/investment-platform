import assert from "node:assert/strict";
import test from "node:test";

import { researchRunCommandNavigation } from "./research-run-command-navigation.ts";

test("active research commands refresh and completed commands open audit", () => {
  assert.deepEqual(researchRunCommandNavigation("queued", null), {
    kind: "refresh",
  });
  assert.deepEqual(researchRunCommandNavigation("running", null), {
    kind: "refresh",
  });
  assert.deepEqual(
    researchRunCommandNavigation(
      "completed",
      "66666666-6666-4666-8666-666666666666",
    ),
    {
      kind: "open_research_run",
      href: "/research-runs/66666666-6666-4666-8666-666666666666",
    },
  );
  assert.deepEqual(researchRunCommandNavigation("failed", null), {
    kind: "stop",
  });
  assert.deepEqual(researchRunCommandNavigation("blocked", null), {
    kind: "stop",
  });
});

test("research command polling pauses at bounded attempts or elapsed time", () => {
  assert.deepEqual(researchRunCommandNavigation("queued", null, 39, 119_999), {
    kind: "refresh",
  });
  assert.deepEqual(researchRunCommandNavigation("queued", null, 40, 0), {
    kind: "pause",
  });
  assert.deepEqual(researchRunCommandNavigation("running", null, 1, 120_000), {
    kind: "pause",
  });
});

test("historical v1 commands never poll after runtime quarantine", () => {
  assert.deepEqual(
    researchRunCommandNavigation(
      "queued",
      null,
      0,
      0,
      "research_run_command_receipt.v1",
    ),
    { kind: "stop" },
  );
  assert.deepEqual(
    researchRunCommandNavigation(
      "running",
      null,
      0,
      0,
      "research_run_command_receipt.v1",
    ),
    { kind: "stop" },
  );
});
