import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  parseValuationSnapshot,
  type ValuationSnapshot,
} from "../../../packages/types/valuation-snapshot.ts";

import { createValuationSnapshotLoader } from "./valuation-snapshot-loader.ts";

const snapshotFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/valuation_snapshot/v1/valid-aligned.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as ValuationSnapshot;

test("an authenticated operator loads their canonical Valuation Snapshot for one Research Run", async () => {
  const requests: Array<{ operatorId: string; runId: string }> = [];
  const loadSnapshot = createValuationSnapshotLoader(
    async (operatorId, runId) => {
      requests.push({ operatorId, runId });
      return { canonical_snapshot: snapshotFixture };
    },
    parseValuationSnapshot,
  );

  const loaded = await loadSnapshot(
    snapshotFixture.operator_id,
    snapshotFixture.research_run_id,
  );

  assert.deepEqual(requests, [
    {
      operatorId: snapshotFixture.operator_id,
      runId: snapshotFixture.research_run_id,
    },
  ]);
  assert.deepEqual(loaded, snapshotFixture);
});

test("Valuation Snapshot loading rejects a row outside requested owner scope", async () => {
  const loadSnapshot = createValuationSnapshotLoader(
    async () => ({ canonical_snapshot: snapshotFixture }),
    parseValuationSnapshot,
  );

  await assert.rejects(
    loadSnapshot(
      "11111111-1111-4111-8111-111111111111",
      snapshotFixture.research_run_id,
    ),
    /outside requested owner or Research Run scope/,
  );
});
