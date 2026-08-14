import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("desktop Moomoo connection remembers client IDs and renders a reusable picker", () => {
  const actions = readFileSync(
    new URL("../app/moomoo-actions.ts", import.meta.url),
    "utf8",
  );
  const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
  const picker = readFileSync(
    new URL("../components/moomoo-client-id-picker.tsx", import.meta.url),
    "utf8",
  );
  const reconnect = readFileSync(
    new URL("../components/moomoo-auto-reconnect.tsx", import.meta.url),
    "utf8",
  );
  const desktop = readFileSync(new URL("./moomoo-desktop.ts", import.meta.url), "utf8");

  assert.match(actions, /MOOMOO_CLIENT_IDS_COOKIE/);
  assert.match(actions, /addMoomooClientId/);
  assert.match(actions, /cookieStore\.set/);
  assert.ok(
    actions.indexOf("await beginMoomooDesktopConnection") <
      actions.indexOf("cookieStore.set"),
  );
  assert.match(page, /parseMoomooClientIds/);
  assert.match(page, /<MoomooClientIdPicker savedClientIds=\{savedClientIds\}/);
  assert.match(page, /<MoomooAutoReconnect/);
  assert.match(page, /clientId=\{autoResumeClientId\}/);
  assert.match(page, /parseMoomooAutoResumeClientId\(autoResumePreference\)/);
  assert.doesNotMatch(page, /savedClientIds\[0\]/);
  assert.match(actions, /MOOMOO_AUTO_RESUME_COOKIE/);
  assert.match(actions, /resumeMoomooDesktopConnection/);
  assert.match(reconnect, /resumeMoomooSilently/);
  assert.match(reconnect, /useEffect/);
  assert.match(picker, /name="clientId"/);
  assert.match(picker, /Use another client ID/);
  assert.match(page, /one concrete[\s\S]+accid:&lt;account-id&gt;/);
  assert.match(page, /moomooStatus\.canReadPortfolio/);
  assert.match(page, /functions stay blocked when either is absent/);
  assert.match(desktop, /moomoo_write_scope_not_permitted/);
  assert.match(desktop, /Turn off Select all, Watchlists, and Trade Execution/);
  assert.doesNotMatch(actions + picker, /password|refresh_token|access_token/i);
});
