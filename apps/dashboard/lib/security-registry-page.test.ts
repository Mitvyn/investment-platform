import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Settings Security Registry shows empty, failed, and unmatched-ticker onboarding states", () => {
  const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

  assert.match(page, /security_registry_error\?: string/);
  assert.match(page, /No research tickers registered locally yet/);
  assert.match(page, /Could not update desktop Security Registry/);
  assert.match(page, /aria-live="polite"/);
  assert.match(page, /Register for Research/);
  assert.match(page, /name="ticker" type="hidden" value=\{entry\.ticker\}/);
  assert.match(page, /name="view" type="hidden" value="settings"/);
});
