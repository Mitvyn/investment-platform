import assert from "node:assert/strict";
import test from "node:test";

import { workflowJobNavigation } from "./workflow-job-navigation.ts";

test("active jobs refresh, completed jobs open security, and failures stop", () => {
  assert.deepEqual(workflowJobNavigation("queued", null), { kind: "refresh" });
  assert.deepEqual(workflowJobNavigation("running", null), { kind: "refresh" });
  assert.deepEqual(
    workflowJobNavigation(
      "completed",
      "22222222-2222-4222-8222-222222222222",
    ),
    {
      kind: "open_security",
      href: "/?security=22222222-2222-4222-8222-222222222222",
    },
  );
  assert.deepEqual(workflowJobNavigation("failed", null), { kind: "stop" });
});

test("active job polling pauses after the bounded refresh budget", () => {
  assert.deepEqual(workflowJobNavigation("queued", null, 39), {
    kind: "refresh",
  });
  assert.deepEqual(workflowJobNavigation("queued", null, 40), {
    kind: "pause",
  });
  assert.deepEqual(workflowJobNavigation("running", null, 40), {
    kind: "pause",
  });
});

test("active job polling pauses at two-minute wall-clock deadline", () => {
  assert.deepEqual(workflowJobNavigation("queued", null, 1, 119_999), {
    kind: "refresh",
  });
  assert.deepEqual(workflowJobNavigation("queued", null, 1, 120_000), {
    kind: "pause",
  });
  assert.deepEqual(workflowJobNavigation("running", null, 1, 120_001), {
    kind: "pause",
  });
});
