import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("importResearchCaptureAction verifies securityId against the server-owned security directory before any import", () => {
  const actions = readFileSync(
    new URL("../app/research-capture-import-actions.ts", import.meta.url),
    "utf8",
  );

  assert.match(actions, /auth\.getClaims\(\)/);
  assert.match(actions, /loadSecurityDirectory/);
  assert.match(actions, /isCanonicalSecurityKnown/);
  assert.match(actions, /security_unauthorized/);
  assert.doesNotMatch(actions, /formData\.get\("cik"\)|formData\.get\("issuerName"\)|formData\.get\("primaryListingExchange"\)/);

  const directoryCallIndex = actions.indexOf("loadSecurityDirectory(");
  const ownershipCheckIndex = actions.indexOf("isCanonicalSecurityKnown(");
  const importCallIndex = actions.indexOf("importResearchCapture(");
  assert.ok(directoryCallIndex >= 0 && ownershipCheckIndex >= 0 && importCallIndex >= 0);
  assert.ok(
    directoryCallIndex < ownershipCheckIndex,
    "security directory must be loaded before the ownership check",
  );
  assert.ok(
    ownershipCheckIndex < importCallIndex,
    "ownership must be verified before any capture import",
  );
});

test("importResearchCaptureAction uses uploaded archive and server-owned identity", () => {
  const actions = readFileSync(
    new URL("../app/research-capture-import-actions.ts", import.meta.url),
    "utf8",
  );

  assert.match(actions, /formData\.get\("captureArchive"\)/);
  assert.match(actions, /importResearchCaptureUpload/);
  assert.match(actions, /confirmEmbeddedIssuerHosts/);
  assert.doesNotMatch(actions, /formData\.get\("cik"\)/);
  assert.doesNotMatch(actions, /formData\.get\("issuerName"\)/);
  const uploadIndex = actions.indexOf("importResearchCaptureUpload(");
  const canonicalCikIndex = actions.indexOf("cik: security.cik");
  const canonicalIssuerIndex = actions.indexOf("issuerName: security.companyName");
  assert.ok(uploadIndex >= 0);
  assert.ok(canonicalCikIndex > uploadIndex);
  assert.ok(canonicalIssuerIndex > uploadIndex);
});

test("importResearchCaptureAction can prepare an imported capture for immediate Research Run launch", () => {
  const actions = readFileSync(
    new URL("../app/research-capture-import-actions.ts", import.meta.url),
    "utf8",
  );

  assert.match(actions, /prepareResearch/);
  assert.match(actions, /launchResearchRun/);
  assert.match(actions, /captureSelection/);
  assert.match(actions, /importedCapture\.captureId/);
  assert.match(actions, /importedCapture\.captureContentHash/);
});
