import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("ticker workspace shows selected-security Research Run history before launcher", () => {
  const page = readFileSync(
    new URL("../app/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(page, /loadResearchRunHistory/);
  assert.match(
    page,
    /loadResearchRunHistory\(\s*operatorId,\s*selectedSecurity\.securityId,\s*\)/,
  );
  assert.match(
    page,
    /<ResearchRunHistoryPanel presentation=\{researchHistoryPresentation\} \/>/,
  );
  assert.ok(
    page.indexOf("<ResearchRunHistoryPanel") <
      page.indexOf("Research Run preflight"),
  );
});
