import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Moomoo mirror persistence stays server-owned and outside connection Settings", () => {
  const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
  const actions = readFileSync(
    new URL("../app/moomoo-actions.ts", import.meta.url),
    "utf8",
  );

  assert.doesNotMatch(page, /action=\{saveMoomooMirror\}/);
  assert.doesNotMatch(page, /Save hosted mirror/);
  assert.match(actions, /auth\.getClaims\(\)/);
  assert.match(actions, /composeMoomooDesktopSnapshots/);
  assert.match(actions, /persistMoomooPortfolioMirror/);
  assert.match(actions, /supabase\.rpc/);
  assert.doesNotMatch(page + actions, /IROS_SUPABASE_SECRET_KEY/);
});
