import assert from "node:assert/strict";
import test from "node:test";

import { presentEvidenceGap } from "./evidence-gap-row-model.ts";

test("evidence gap presentation makes missing context compact and explicit", () => {
  assert.deepEqual(presentEvidenceGap("Forward catalyst"), {
    label: "Forward catalyst",
    state: "missing",
    stateLabel: "Missing",
  });
});
