import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Research Overview exposes a capture-import path that feeds the existing accepted-capture selector", () => {
  const page = readFileSync(
    new URL("../app/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(page, /Accepted evidence capture/);
  assert.match(page, /Import a collected capture archive/);
  assert.match(
    page,
    /This does not acquire sources, browse the web,\s+or\s+call a provider or model/,
  );
  assert.match(page, /action=\{importResearchCaptureAction\}/);
  assert.match(page, /name="securityId"/);
  assert.match(page, /name="archivePath"/);
  assert.match(page, /name="captureArchive"/);
  assert.match(page, /type="file"/);
  assert.match(page, /name="confirmEmbeddedIssuerHosts"/);
  assert.match(page, /The app derives cutoff and issuer hosts from the archive/);
  assert.match(page, /name="captureAsOfCutoff"/);
  assert.match(page, /name="trustedIssuerHosts"/);
  assert.match(page, /params\.capture_import === "accepted"/);
  assert.match(page, /params\.capture_import_error/);
  assert.match(page, /capture_import\?: string/);
  assert.match(page, /capture_import_error\?: string/);
  assert.doesNotMatch(page, /name="(cik|issuerName|primaryListingExchange|operatorId)"/);

  const importCardIndex = page.indexOf("Accepted evidence capture");
  const preflightCardIndex = page.indexOf("Research Run preflight");
  assert.ok(importCardIndex >= 0 && preflightCardIndex >= 0);
  assert.ok(
    importCardIndex < preflightCardIndex,
    "capture import should render above the existing launcher preflight card",
  );
});
