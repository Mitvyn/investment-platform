import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("ordinary Research Run loader cannot query raw provider payloads", () => {
  const source = readFileSync(
    new URL("./grader-executions.ts", import.meta.url),
    "utf8",
  );

  assert.match(source, /iros_v_research_run_grader_executions/);
  assert.doesNotMatch(
    source,
    /iros_model_attempt_payloads|raw_request|raw_response|reasoning_content/,
  );
});
