import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("dashboard exposes an authenticated fixed-contract Research Run launcher", () => {
  const page = readFileSync(
    new URL("../app/page.tsx", import.meta.url),
    "utf8",
  );
  const actions = readFileSync(
    new URL("../app/research-actions.ts", import.meta.url),
    "utf8",
  );

  assert.match(page, /action=\{launchResearchRun\}/);
  assert.match(page, /name="securityId"/);
  assert.match(page, /name="asOfCutoff"/);
  assert.match(page, /name="operatorFocus"/);
  assert.match(page, /biotech_moonshot_catalyst_assessment/);
  assert.match(page, /Research Run preflight/);
  assert.match(page, /blocking_reason_codes/);
  assert.match(actions, /auth\.getClaims\(\)/);
  assert.match(actions, /enqueueResearchRunCommand/);
  assert.match(actions, /research_command=/);
  assert.doesNotMatch(page + actions, /OPENAI_API_KEY|DEEPSEEK_API_KEY/);
  assert.doesNotMatch(page + actions, /child_process|workers\/|fetch\(/);
});

test("launcher presents blocked commands as policy gates, not completed research", () => {
  const page = readFileSync(
    new URL("../app/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(page, /Launch blocked/);
  assert.match(page, /No evidence, market, or model execution was started/);
  assert.doesNotMatch(page, /Buy|Position size|Target price/);
});
