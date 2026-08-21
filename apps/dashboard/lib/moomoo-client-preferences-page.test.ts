import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("desktop Moomoo connection remembers client IDs without presenting security data", () => {
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
  assert.match(actions, /discoverMoomooMcpTools/);
  assert.match(actions, /beginMoomooMcpAuthorization/);
  assert.match(reconnect, /resumeMoomooSilently/);
  assert.match(reconnect, /useEffect/);
  assert.match(picker, /name="clientId"/);
  assert.match(picker, /Use another client ID/);
  assert.match(page, /Extra broker grants never enable new app functions/);
  assert.match(page, /disconnect and[\s\S]+reconnect to refresh this status/);
  assert.match(page, /loadMoomooMcpDiscoveryStatus/);
  assert.match(page, /discoverMoomooMcp/);
  assert.match(page, /authorizeMoomooMcp/);
  assert.match(page, /OpenAPI connection does not authorize MCP/);
  assert.match(desktop, /Trade execution/);
  assert.doesNotMatch(page, /action=\{saveMoomooMirror\}/);
  assert.doesNotMatch(page, /action=\{refreshMoomoo\}/);
  assert.doesNotMatch(page, /Start live quote/);
  assert.doesNotMatch(actions + picker, /password|refresh_token|access_token/i);
});

test("Moomoo MCP tool names stay collapsed behind a discoverable list", () => {
  const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

  assert.match(page, /<details[\s\S]*<summary[\s\S]*discovered tools/i);
  assert.match(page, /moomooMcpStatus\.tools\.map/);
  assert.doesNotMatch(
    page,
    /moomooMcpStatus\.tools\.map\(\(tool\) => tool\.name\)\.join/,
  );
});
