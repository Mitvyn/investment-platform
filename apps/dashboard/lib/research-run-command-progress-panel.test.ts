import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const panel = readFileSync(
  new URL(
    "../components/research-run-command-progress-panel.tsx",
    import.meta.url,
  ),
  "utf8",
);

test("progress panel consumes presentation only and renders complete command audit", () => {
  assert.match(
    panel,
    /presentation: ResearchRunCommandProgressPresentation/,
  );
  assert.doesNotMatch(panel, /createClient|supabase|fetch\(/i);
  assert.match(panel, /presentation\.status\.label/);
  assert.match(panel, /presentation\.attempt/);
  assert.match(panel, /presentation\.activeStage/);
  assert.match(panel, /presentation\.completedStages\.map/);
  assert.match(panel, /checkpoint\.ordinal/);
  assert.match(panel, /presentation\.lease\.label/);
  assert.match(panel, /presentation\.lease\.expiresAt/);
  assert.match(panel, /presentation\.failure\.errorCode/);
  assert.match(panel, /presentation\.failure\.retryable/);
});

test("progress panel keeps blocked, queued, retry, and terminal states explicit", () => {
  assert.match(
    panel,
    /Preflight blocked\. No worker attempt or workflow stage started\./,
  );
  assert.match(panel, /Queued and waiting for first worker claim\./);
  assert.match(panel, /Retry queued after a retryable worker attempt\./);
  assert.match(panel, />\s*Terminal failure\s*</);
  assert.match(panel, />\s*No stage checkpoint persisted\.\s*</);
});
