import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("./research-run-command-progress.ts", import.meta.url),
  "utf8",
);

test("command progress reads one canonical owner-scoped view without raw workflow tables", () => {
  assert.match(
    source,
    /\.from\("iros_v_research_run_command_progress"\)/,
  );
  assert.match(
    source,
    /\.select\("operator_id,command_id,canonical_progress"\)/,
  );
  assert.match(source, /\.eq\("operator_id", operatorId\)/);
  assert.match(source, /\.eq\("command_id", commandId\)/);
  assert.match(source, /\.limit\(2\)/);
  assert.match(source, /createResearchRunCommandProgressLoader/);
  assert.doesNotMatch(
    source,
    /iros_research_run_command_(attempts|checkpoints)|raw_provider|raw_payload/,
  );
});

test("command progress hides provider and database error details", () => {
  assert.match(
    source,
    /throw new Error\("Research Run command progress unavailable"\)/,
  );
  assert.doesNotMatch(source, /error\.message/);
});
