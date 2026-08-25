import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

test("the page sanitises the quant error code from the query string", () => {
  // A raw `params.quant_error` would render whatever a crafted link contained.
  assert.match(source, /quantErrorCodeFromQuery\(params\.quant_error\)/);
  assert.doesNotMatch(source, /errorCode: params\.quant_error/);
});

test("the quant workspace is loaded only for the quant section and one security", () => {
  assert.match(source, /activeSection === "quant" && selectedSecurity/);
  assert.match(source, /loadQuantDatasetStatus/);
  assert.match(source, /loadLatestQuantResult/);
});

test("only the canonical security identity crosses into the quant workspace", () => {
  const block = source.slice(
    source.indexOf("const quantIdentity"),
    source.indexOf("const quantView"),
  );
  assert.ok(block.length > 0);
  assert.match(block, /securityId: selectedSecurity\.securityId/);
  assert.match(block, /operatorId/);
  for (const forbidden of [
    "holdings",
    "portfolio",
    "moomoo",
    "ticker",
    "watchlist",
    "researchFlow",
    "fund",
  ]) {
    assert.doesNotMatch(
      block,
      new RegExp(forbidden, "i"),
      `${forbidden} must not cross into the quant workspace`,
    );
  }
});

test("the quant panel receives no research, portfolio, or broker props", () => {
  const start = source.indexOf("<QuantPanel");
  const block = source.slice(start, source.indexOf("/>", start));
  assert.ok(start > 0);
  assert.deepEqual(
    block
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0 && line !== "<QuantPanel"),
    [
      "securityId={selectedSecurity?.securityId ?? null}",
      "ticker={ticker}",
      "view={quantView}",
    ],
  );
});
