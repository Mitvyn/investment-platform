import assert from "node:assert/strict";
import test from "node:test";

import { marketPriceFormat } from "./market-price-presentation.ts";

test("preserves cents for market prices at or above ten dollars", () => {
  assert.deepEqual(marketPriceFormat([12.34, 10.01]), {
    type: "price",
    precision: 2,
    minMove: 0.01,
  });
});
