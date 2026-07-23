import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("dashboard exposes authenticated security onboarding without worker secrets", () => {
  const page = readFileSync(
    new URL("../app/page.tsx", import.meta.url),
    "utf8",
  );
  const actions = readFileSync(
    new URL("../app/security-actions.ts", import.meta.url),
    "utf8",
  );

  assert.match(page, /action=\{registerSecurity\}/);
  assert.match(page, /name="ticker"/);
  assert.match(page, /Add security/);
  assert.match(actions, /auth\.getClaims\(\)/);
  assert.match(actions, /enqueueSecurityRegistration/);
  assert.match(actions, /registration=/);
  assert.doesNotMatch(page + actions, /IROS_SUPABASE_SECRET_KEY/);
  assert.doesNotMatch(page + actions, /child_process/);
  assert.doesNotMatch(page + actions, /workers\/security_registry/);
});
