import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Research Overview exposes a ticker-scoped notebook with empty, notes, and error states", () => {
  const page = readFileSync(
    new URL("../app/page.tsx", import.meta.url),
    "utf8",
  );
  const actions = readFileSync(
    new URL("../app/research-notebook-actions.ts", import.meta.url),
    "utf8",
  );

  assert.match(page, /Ticker notebook/);
  assert.match(page, /Research Notebook/);
  assert.match(
    page,
    /Automated ticker agent is not active\. Notes stay scoped\s+to\s+this security\./,
  );
  assert.match(page, /Not AI\s+research, agent output, or a trade signal/);
  assert.match(page, /tickerNotebook\.notes\.map/);
  assert.match(page, /tickerNotebook\.detail/);
  assert.match(page, /note\.noteId/);
  assert.match(page, /note\.body/);
  assert.match(page, /note\.createdAt/);
  assert.match(page, /action=\{addResearchNotebookNote\}/);
  assert.match(page, /name="securityId"/);
  assert.match(page, /name="body"/);
  assert.match(page, /maxLength=\{4000\}/);
  assert.match(page, /params\.notebook_error/);
  assert.match(page, /notebook_error\?: string/);
  assert.match(actions, /auth\.getClaims\(\)/);
  assert.match(actions, /addTickerNotebookNote/);
  assert.match(actions, /notebook_error/);
  assert.doesNotMatch(page + actions, /child_process|workers\/|fetch\(/);
});

test("addResearchNotebookNote verifies securityId against the server-owned security directory before writing", () => {
  const actions = readFileSync(
    new URL("../app/research-notebook-actions.ts", import.meta.url),
    "utf8",
  );

  assert.match(actions, /loadSecurityDirectory/);
  assert.match(actions, /isCanonicalSecurityKnown/);
  assert.match(actions, /security_unauthorized/);

  const directoryCallIndex = actions.indexOf("loadSecurityDirectory(");
  const ownershipCheckIndex = actions.indexOf("isCanonicalSecurityKnown(");
  const writeCallIndex = actions.indexOf("addTickerNotebookNote(");
  assert.ok(directoryCallIndex >= 0 && ownershipCheckIndex >= 0 && writeCallIndex >= 0);
  assert.ok(
    directoryCallIndex < ownershipCheckIndex,
    "security directory must be loaded before the ownership check",
  );
  assert.ok(
    ownershipCheckIndex < writeCallIndex,
    "ownership must be verified before any notebook write",
  );
});
