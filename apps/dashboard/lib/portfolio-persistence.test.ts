import assert from "node:assert/strict";
import test from "node:test";

import {
  PortfolioPersistenceError,
  persistMoomooPortfolioMirror,
  type MoomooComposition,
} from "./portfolio-persistence.ts";

const operatorId = "11111111-1111-4111-8111-111111111111";
const accountRef = "fc67bfbd-f0a5-5b9f-9012-42dc8e733491";

const composition: MoomooComposition = {
  snapshot_count: 1,
  snapshots: [
    {
      account_label: "Moomoo account 1",
      account_type: "MARGIN",
      security_firm: "Moomoo Financial Singapore",
      snapshot: {
        ambiguous_count: 0,
        captured_at: "2026-08-13T09:30:00+00:00",
        content_sha256: "07345b27c8d4ea93c60dac6677407f54f60ad46157affad15df7358dc8ef1bc6",
        contract_version: "portfolio_snapshot.v1",
        operator_id: operatorId,
        position_count: 1,
        positions: [
          {
            available_quantity: "100",
            average_cost: "1.72",
            average_cost_state: "reported",
            canonical_ticker: "GANX",
            currency: "USD",
            display_name: "Gain Therapeutics",
            last_price: "1.84",
            mapping_state: "mapped",
            market_value: "184",
            ordinal: 1,
            position_id: "33333333-3333-4333-8333-333333333333",
            position_side: "LONG",
            precision_risk_fields: [],
            primary_listing_exchange: "NASDAQ",
            provider_symbol: "US.GANX",
            quantity: "100",
            security_id: "22222222-2222-4222-8222-222222222222",
            snapshot_id: "500832b8-a7fe-5541-af83-58ce445d4b7a",
            unrealized_pnl: "12",
            unrealized_pnl_state: "reported",
          },
        ],
        precision_risk_count: 0,
        provider: "moomoo_rest",
        provider_transport: "web_rest_oauth",
        read_only_assurance: "read_only_scopes_no_order_surface",
        snapshot_id: "500832b8-a7fe-5541-af83-58ce445d4b7a",
        account_ref: accountRef,
        unmapped_count: 0,
      },
    },
  ],
};

test("persists one composed account through owner-authenticated RPC", async () => {
  const calls: Array<[string, Record<string, unknown>]> = [];
  const result = await persistMoomooPortfolioMirror({
    operatorId,
    checkedAt: new Date("2026-08-13T09:31:00Z"),
    composition,
    rpc: async (name, parameters) => {
      calls.push([name, parameters]);
      return {
        data: {
          account_ref: accountRef,
          checked_at: "2026-08-13T09:31:00+00:00",
          idempotency_key: String(parameters.p_idempotency_key),
          outcome: "created",
          receipt_id: "55555555-5555-4555-8555-555555555555",
          request_sha256: String(parameters.p_request_sha256),
          snapshot_id: "500832b8-a7fe-5541-af83-58ce445d4b7a",
          sync_state: "complete",
        },
        error: null,
      };
    },
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "iros_persist_portfolio_broker_snapshot");
  assert.equal(calls[0][1].p_operator_id, operatorId);
  assert.match(String(calls[0][1].p_idempotency_key), /^portfolio-save:/);
  assert.equal(result[0].outcome, "created");
});

test("accepts Python-composed non-ASCII canonical snapshot", async () => {
  const nonAsciiComposition = structuredClone(composition);
  const snapshot = nonAsciiComposition.snapshots[0].snapshot;
  snapshot.content_sha256 =
    "16f943387473e83d30737eba29e45fc80a3dddc6d1ecd1cef1a4b87ef7355b62";
  snapshot.snapshot_id = "a9c921ef-83ec-587c-946c-ebc22b4d4906";
  snapshot.positions[0].display_name = "Moody’s 制 😀";
  snapshot.positions[0].position_id = "e4b532fe-743e-5e33-87ba-737731d87e7f";
  snapshot.positions[0].snapshot_id = snapshot.snapshot_id;
  let called = false;

  await persistMoomooPortfolioMirror({
    operatorId,
    checkedAt: new Date("2026-08-13T09:31:00Z"),
    composition: nonAsciiComposition,
    rpc: async (_name, parameters) => {
      called = true;
      return {
        data: {
          account_ref: accountRef,
          checked_at: "2026-08-13T09:31:00+00:00",
          idempotency_key: String(parameters.p_idempotency_key),
          outcome: "created",
          receipt_id: "55555555-5555-4555-8555-555555555555",
          request_sha256: String(parameters.p_request_sha256),
          snapshot_id: snapshot.snapshot_id,
          sync_state: "complete",
        },
        error: null,
      };
    },
  });

  assert.equal(called, true);
});

test("maps database detail to one safe persistence error", async () => {
  await assert.rejects(
    persistMoomooPortfolioMirror({
      operatorId,
      checkedAt: new Date("2026-08-13T09:31:00Z"),
      composition,
      rpc: async () => ({
        data: null,
        error: { message: "relation iros_portfolio_broker_snapshots failed" },
      }),
    }),
    (error: unknown) =>
      error instanceof PortfolioPersistenceError && error.code === "persist_failed",
  );
});
