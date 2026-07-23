import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const graderFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/grader_execution/v1/accepted-moonshot.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, any>;

const memoFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/committee_memo/v1/valid.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, any>;

test("canonical execution fixtures pin approved prompt families and current candidate models", () => {
  assert.equal(graderFixture.prompt_version, "moonshot_grader_v1");
  assert.equal(
    graderFixture.model_config_id,
    "biotech_committee_graders_openai_sol_medium_v1",
  );
  assert.equal(graderFixture.provider, "openai");
  assert.equal(graderFixture.model, "gpt-5.6-sol");
  assert.equal(graderFixture.attempts[0].prompt_version, "moonshot_grader_v1");
  assert.equal(graderFixture.attempts[0].model, "gpt-5.6-sol");

  assert.equal(
    memoFixture.execution_metadata.prompt_version,
    "committee_reconcile_v1",
  );
  assert.equal(
    memoFixture.execution_metadata.model_config_id,
    "biotech_committee_synthesizer_gpt_5_6_sol_medium_v1",
  );
  assert.equal(memoFixture.execution_metadata.provider, "openai");
  assert.equal(memoFixture.execution_metadata.model, "gpt-5.6-sol");
});
