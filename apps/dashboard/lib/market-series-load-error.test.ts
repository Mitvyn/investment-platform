import assert from "node:assert/strict";
import test from "node:test";

import { marketSeriesUnavailableReason } from "./market-series-load-error.ts";

test("does not label an access failure as an unapplied migration", () => {
  assert.equal(
    marketSeriesUnavailableReason({ code: "42501" }),
    "Market-series query failed. Check authenticated access, then retry.",
  );
});

test("identifies only missing market-series relations as migration work", () => {
  assert.equal(
    marketSeriesUnavailableReason({ code: "42P01" }),
    "Market-series storage is not migrated.",
  );
  assert.equal(
    marketSeriesUnavailableReason({ code: "PGRST205" }),
    "Market-series storage is not migrated.",
  );
});
