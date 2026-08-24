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
  assert.match(page, /Never required for Moomoo connection/);
  assert.match(page, /its own failure never affects the\s+connection above/);
  assert.match(desktop, /Trade execution/);
  assert.doesNotMatch(page, /action=\{saveMoomooMirror\}/);
  assert.doesNotMatch(page, /action=\{refreshMoomoo\}/);
  assert.doesNotMatch(page, /Start live quote/);
  assert.doesNotMatch(actions + picker, /password|refresh_token|access_token/i);
});

test("MCP is the one primary Moomoo connection; OpenAPI streaming is secondary and auto-resumes silently", () => {
  const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
  const actions = readFileSync(
    new URL("../app/moomoo-actions.ts", import.meta.url),
    "utf8",
  );
  const mcpReconnect = readFileSync(
    new URL("../components/moomoo-mcp-auto-reconnect.tsx", import.meta.url),
    "utf8",
  );

  // Exactly one primary "Connect Moomoo" action, and it fires MCP
  // authorization, not the OpenAPI connect flow.
  assert.equal((page.match(/>\s*Connect Moomoo\s*</g) ?? []).length, 1);
  assert.match(page, /authorizeMoomooMcp[\s\S]*?Connect Moomoo/);

  // Optional OpenAPI streaming is labeled and scoped as secondary.
  assert.match(page, /Enable streaming quotes \(optional\)/);
  assert.match(page, /<details[\s\S]*Enable streaming quotes \(optional\)[\s\S]*<\/details>/);

  // Startup auto-resume for MCP is wired independently of OpenAPI's, but is
  // still gated by its own explicit, independent MCP auto-resume preference
  // (never the OpenAPI cookie names) so an intentional MCP disconnect stops
  // silent resume from firing again on the next page load.
  assert.match(page, /<MoomooMcpAutoReconnect/);
  assert.match(mcpReconnect, /resumeMoomooMcpSilently/);
  assert.match(actions, /export async function resumeMoomooMcpSilently/);
  const resumeMoomooMcpSilentlySlice = actions.slice(
    actions.indexOf("export async function resumeMoomooMcpSilently"),
    actions.indexOf("export async function resumeMoomooMcpSilently") + 600,
  );
  assert.match(resumeMoomooMcpSilentlySlice, /MOOMOO_MCP_AUTO_RESUME_COOKIE/);
  assert.doesNotMatch(
    resumeMoomooMcpSilentlySlice,
    /MOOMOO_AUTO_RESUME_COOKIE|MOOMOO_CLIENT_IDS_COOKIE/,
  );
  assert.match(actions, /export async function authorizeMoomooMcp/);
  assert.match(
    actions.slice(actions.indexOf("export async function authorizeMoomooMcp")),
    /MOOMOO_MCP_AUTO_RESUME_COOKIE,\s*"enabled"/,
  );
  assert.match(actions, /export async function disconnectMoomooMcpAction/);
  assert.match(
    actions.slice(actions.indexOf("export async function disconnectMoomooMcpAction")),
    /MOOMOO_MCP_AUTO_RESUME_COOKIE,\s*"disabled"/,
  );

  // Settings never shows securities or holdings inside connection detail.
  const settingsCardStart = page.indexOf("Connect Moomoo");
  const settingsCardEnd = page.indexOf("Clear all local Moomoo access");
  const connectionCard = page.slice(settingsCardStart, settingsCardEnd);
  assert.doesNotMatch(connectionCard, /MoomooHoldingsTable/);
});

test("Moomoo MCP tool names stay collapsed behind a discoverable list, honestly labeled as raw provider inventory", () => {
  const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

  assert.match(page, /<details[\s\S]*<summary[\s\S]*provider tool inventory/i);
  assert.match(page, /moomooMcpStatus\.tools\.map/);
  assert.doesNotMatch(
    page,
    /moomooMcpStatus\.tools\.map\(\(tool\) => tool\.name\)\.join/,
  );

  // Discovery lists the provider's raw inventory; it must never be labeled
  // as if discovery itself proves a tool is read-only or callable, and the
  // app-approved callable tool must be shown separately from that list.
  assert.doesNotMatch(page, /read tools|read-tool/i);
  assert.match(page, /does not make a tool callable/i);
  assert.match(page, /App-approved callable read tool/);
  assert.match(page, /quote_stock_quote/);
});

test("MCP authorization shows bounded actionable failures instead of one generic error", () => {
  const actions = readFileSync(
    new URL("../app/moomoo-actions.ts", import.meta.url),
    "utf8",
  );
  const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

  assert.match(actions, /error instanceof MoomooMcpCommandError/);
  assert.match(actions, /mcp_error=\$\{encodeURIComponent\(errorCode\)\}/);
  assert.match(page, /authorization_metadata_unavailable/);
  assert.match(page, /Could not reach Moomoo OAuth metadata/);
  assert.match(page, /moomoo_system_browser_unavailable/);
});

test("full local clear removes connection preferences but retains research data", () => {
  const actions = readFileSync(
    new URL("../app/moomoo-actions.ts", import.meta.url),
    "utf8",
  );
  const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
  const clearSlice = actions.slice(
    actions.indexOf("export async function disconnectMoomooAllAction"),
  );

  assert.match(clearSlice, /cookieStore\.delete\(MOOMOO_AUTO_RESUME_COOKIE\)/);
  assert.match(clearSlice, /cookieStore\.delete\(MOOMOO_MCP_AUTO_RESUME_COOKIE\)/);
  assert.match(clearSlice, /cookieStore\.delete\(MOOMOO_CLIENT_IDS_COOKIE\)/);
  assert.match(page, /Clear all local Moomoo access/);
  assert.match(page, /keeps research\s+tickers, notes, and portfolio snapshots/i);
  assert.match(page, /does not revoke\s+access at Moomoo/i);
});
