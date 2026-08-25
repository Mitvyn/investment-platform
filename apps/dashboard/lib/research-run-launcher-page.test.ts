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
  assert.match(page, /name="operatorFocus"/);
  assert.doesNotMatch(page, /name="asOfCutoff"/);
  assert.doesNotMatch(page, /name="researchContract"/);
  assert.match(page, /licensed official close/);
  assert.match(page, /personal EOD/);
  assert.match(page, /capture\.as_of_cutoff/);
  assert.match(page, /Not\s+institutional-grade or for trade execution/);
  assert.match(page, /Research Run preflight/);
  assert.match(page, /name="captureSelection"/);
  assert.match(page, /Select accepted evidence/);
  assert.match(page, /acceptedCaptureList\.detail/);
  assert.match(page, /disabled=\{acceptedCaptureList\.captures\.length === 0\}/);
  assert.match(page, /defaultValue=""/);
  assert.match(page, /blocking_reason_codes/);
  assert.match(actions, /auth\.getClaims\(\)/);
  assert.match(actions, /enqueueResearchRunCommand/);
  assert.match(actions, /enqueueLocalResearchRunCommand/);
  assert.match(actions, /isLocalResearchRuntimeReady/);
  assert.match(actions, /loadSecurityDirectory/);
  assert.match(actions, /parseAcceptedResearchCaptureSelection/);
  assert.match(actions, /resolveAcceptedResearchCapture/);
  assert.match(actions, /formData\.get\("captureSelection"\)/);
  assert.match(actions, /buildResearchRequestFromAcceptedCapture/);
  assert.doesNotMatch(actions, /formData\.get\("asOfCutoff"\)/);
  assert.doesNotMatch(actions, /formData\.get\("researchContract"\)/);
  assert.match(actions, /research_command=/);
  assert.doesNotMatch(page, /name="capture(?:Id|Revision|ContentHash)"/);
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

test("launcher labels historical v1 commands as retired and non-executable", () => {
  const page = readFileSync(
    new URL("../app/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(page, /Historical command retired/);
  assert.match(page, /Capture-bound v2 command required for execution/);
  assert.match(
    page,
    /visibleResearchCommand\?\.contract_version === "research_run_command_receipt\.v2"/,
  );
});
