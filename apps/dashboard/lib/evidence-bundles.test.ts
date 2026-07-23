import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { EvidenceBundle } from "../../../packages/types/evidence-bundle.ts";

import { createEvidenceBundleLoader } from "./evidence-bundles.ts";

const bundleFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/evidence_bundle/v1/grader-ready.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as EvidenceBundle;

test("an authenticated operator loads their canonical Evidence Bundle for one Research Run", async () => {
  const requests: Array<{ operatorId: string; runId: string }> = [];
  const loadEvidenceBundle = createEvidenceBundleLoader(
    async (operatorId, runId) => {
      requests.push({ operatorId, runId });
      return { canonical_bundle: bundleFixture };
    },
  );

  const loaded = await loadEvidenceBundle(
    bundleFixture.operator_id,
    bundleFixture.research_run_id,
  );

  assert.deepEqual(requests, [
    {
      operatorId: bundleFixture.operator_id,
      runId: bundleFixture.research_run_id,
    },
  ]);
  assert.deepEqual(loaded, bundleFixture);
});

test("Evidence Bundle loading rejects a row outside requested owner scope", async () => {
  const loadEvidenceBundle = createEvidenceBundleLoader(async () => ({
    canonical_bundle: bundleFixture,
  }));

  await assert.rejects(
    loadEvidenceBundle(
      "11111111-1111-4111-8111-111111111111",
      bundleFixture.research_run_id,
    ),
    /outside requested owner or Research Run scope/,
  );
});
