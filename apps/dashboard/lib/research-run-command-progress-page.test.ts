import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("ticker workspace renders canonical command progress when available", () => {
  const page = readFileSync(
    new URL("../app/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(page, /loadResearchRunCommandProgress/);
  assert.match(page, /presentResearchRunCommandProgress/);
  assert.match(
    page,
    /loadResearchRunCommandProgress\(\s*operatorId,\s*visibleResearchCommand\.command_id,\s*\)/,
  );
  assert.match(
    page,
    /<ResearchRunCommandProgressPanel\s+presentation=\{researchCommandProgressPresentation\}/,
  );
  assert.match(page, /\.catch\(\(\) => null\)/);
});
