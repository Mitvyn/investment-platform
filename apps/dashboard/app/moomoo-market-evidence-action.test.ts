import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

const source = readFileSync(
  fileURLToPath(new URL("./moomoo-actions.ts", import.meta.url)),
  "utf8",
);

test("refreshMarketEvidence verifies the security directory before calling the MCP adapter", () => {
  const actionStart = source.indexOf("export async function refreshMarketEvidence");
  assert.notEqual(actionStart, -1);
  const actionBody = source.slice(actionStart, source.indexOf("\n}\n", actionStart));

  const directoryLookupIndex = actionBody.indexOf("iros_securities");
  const symbolValidationIndex = actionBody.indexOf(
    "/^[A-Z][A-Z0-9.\\-]{0,15}$/.test(security.symbol)",
  );
  const adapterCallIndex = actionBody.indexOf("fetchMoomooMarketQuoteEvidence(");

  assert.ok(directoryLookupIndex > -1);
  assert.ok(symbolValidationIndex > -1);
  assert.ok(adapterCallIndex > -1);
  assert.ok(directoryLookupIndex < symbolValidationIndex);
  assert.ok(symbolValidationIndex < adapterCallIndex);
});

test("refreshMarketEvidence never forwards a client-supplied ticker to the adapter", () => {
  const actionStart = source.indexOf("export async function refreshMarketEvidence");
  const actionBody = source.slice(actionStart, source.indexOf("\n}\n", actionStart));
  assert.doesNotMatch(actionBody, /formData\.get\("ticker"\)/);
  assert.match(actionBody, /ticker: `US\.\$\{security\.symbol\}`/);
});
