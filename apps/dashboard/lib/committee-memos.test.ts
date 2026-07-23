import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("committee memo loader reads owner-scoped canonical view without raw provider bodies", () => {
  const source = readFileSync(
    new URL("./committee-memos.ts", import.meta.url),
    "utf8",
  );

  assert.match(source, /iros_v_research_run_committee_memos/);
  assert.match(
    source,
    /operator_id,research_run_id,committee_result_id,memo_id,canonical_memo/,
  );
  assert.match(source, /parseCommitteeMemo/);
  assert.doesNotMatch(
    source,
    /raw_request|raw_response|reasoning_content|iros_synthesis_attempt_payloads/,
  );
});
