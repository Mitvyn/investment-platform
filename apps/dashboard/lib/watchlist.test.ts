import assert from "node:assert/strict";
import test from "node:test";

import { resolveWatchlistRows } from "./watchlist-identity.ts";

test("stable watchlist rows render canonical security identity", () => {
  const items = resolveWatchlistRows(
    [
      {
        security_id: "11111111-1111-4111-8111-111111111111",
        ticker: "WRONG",
        company_name: "Untrusted label",
        disposition: "monitor",
        added_at: "2026-07-21T00:00:00Z",
        updated_at: "2026-07-22T00:00:00Z",
      },
    ],
    [
      {
        id: "11111111-1111-4111-8111-111111111111",
        symbol: "RXRX",
        issuer_name: "Recursion Pharmaceuticals, Inc.",
      },
    ],
  );

  assert.equal(items.length, 1);
  assert.equal(items[0]?.ticker, "RXRX");
  assert.equal(items[0]?.companyName, "Recursion Pharmaceuticals, Inc.");
});

test("legacy watchlist rows resolve only through one canonical current symbol", () => {
  const items = resolveWatchlistRows(
    [
      {
        security_id: null,
        ticker: "RXRX",
        company_name: "Untrusted label",
        disposition: "deep_research",
        added_at: "2026-07-21T00:00:00Z",
        updated_at: "2026-07-22T00:00:00Z",
      },
    ],
    [
      {
        id: "11111111-1111-4111-8111-111111111111",
        symbol: "RXRX",
        issuer_name: "Recursion Pharmaceuticals, Inc.",
      },
    ],
  );

  assert.equal(items[0]?.securityId, "11111111-1111-4111-8111-111111111111");
  assert.equal(items[0]?.companyName, "Recursion Pharmaceuticals, Inc.");
});

test("stable and legacy aliases collapse to one watchlist security", () => {
  const items = resolveWatchlistRows(
    [
      {
        security_id: "11111111-1111-4111-8111-111111111111",
        ticker: "RXRX",
        company_name: "Stored label",
        disposition: "monitor",
        added_at: "2026-07-21T00:00:00Z",
        updated_at: "2026-07-22T01:00:00Z",
      },
      {
        security_id: null,
        ticker: "RXRX",
        company_name: "Legacy label",
        disposition: "deep_research",
        added_at: "2026-07-20T00:00:00Z",
        updated_at: "2026-07-22T00:00:00Z",
      },
    ],
    [
      {
        id: "11111111-1111-4111-8111-111111111111",
        symbol: "RXRX",
        issuer_name: "Recursion Pharmaceuticals, Inc.",
      },
    ],
  );

  assert.equal(items.length, 1);
  assert.equal(items[0]?.disposition, "monitor");
});
