import assert from "node:assert/strict";
import test from "node:test";

import {
  beginMoomooDesktopConnection,
  composeMoomooDesktopSnapshots,
  disconnectMoomooDesktop,
  loadMoomooDesktopHoldings,
  loadMoomooDesktopQuotes,
  loadMoomooDesktopStatus,
  presentMoomooConnectionSummary,
  presentMoomooCapabilityStates,
  refreshMoomooDesktopHoldings,
  replaceMoomooDesktopQuoteSubscriptions,
  resumeMoomooDesktopConnection,
} from "./moomoo-desktop.ts";

test("connection failure detail overrides an older persisted mirror summary", () => {
  assert.equal(
    presentMoomooConnectionSummary(
      {
        accountCount: 1,
        canReadMarketData: false,
        canReadPortfolio: false,
        detail: "Moomoo returned write access. Reconnect with read-only access.",
        positionCount: 0,
        state: "failed",
        syncState: "failed",
      },
      "Persisted read-only mirror · checked 2 minutes ago",
    ),
    "Connection needs attention · Moomoo returned write access. Reconnect with read-only access.",
  );
});

test("capability matrix keeps partial authorization connected and explains reconnect path", () => {
  assert.deepEqual(
    presentMoomooCapabilityStates({
      accountCount: 0,
      canReadMarketData: true,
      canReadPortfolio: false,
      detail: "Market data connected; holdings unavailable without Accounts & Orders access",
      positionCount: 0,
      state: "connected",
      syncState: "unavailable",
    }),
    [
      {
        detail: "Live quotes available for selected security.",
        id: "market_data",
        label: "Market data",
        state: "enabled",
      },
      {
        detail: "Enable Accounts & Orders for one account, then reconnect.",
        id: "portfolio_holdings",
        label: "Holdings mirror",
        state: "reconnect_required",
      },
      {
        detail: "Not supported by this app. No order or trade-execution path exists.",
        id: "trade_execution",
        label: "Trade execution",
        state: "not_supported",
      },
    ],
  );
});

const desktopEnvironment = {
  IROS_DESKTOP: "1",
  IROS_DESKTOP_CONTROL_ORIGIN: "http://127.0.0.1:61555",
  IROS_DESKTOP_CONTROL_TOKEN: "x".repeat(43),
  IROS_DESKTOP_WORKER_STATE: "ready",
};

test("desktop status stays unavailable without local runtime and makes no request", async () => {
  let called = false;

  const status = await loadMoomooDesktopStatus(
    {},
    async () => {
      called = true;
      throw new Error("must not fetch");
    },
  );

  assert.equal(called, false);
  assert.deepEqual(status, {
    accountCount: 0,
    canReadMarketData: false,
    canReadPortfolio: false,
    detail: "Open desktop app to connect Moomoo",
    positionCount: 0,
    state: "unavailable",
    syncState: "unavailable",
  });
});

test("desktop status maps capability-authenticated worker response", async () => {
  const calls: Array<[string, RequestInit]> = [];

  const status = await loadMoomooDesktopStatus(
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json({
        account_count: 0,
        capabilities: ["market_data"],
        error_code: null,
        position_count: 0,
        state: "connected",
        sync_state: "unavailable",
      });
    },
  );

  assert.deepEqual(status, {
    accountCount: 0,
    canReadMarketData: true,
    canReadPortfolio: false,
    detail: "Market data connected; holdings unavailable without Accounts & Orders access",
    positionCount: 0,
    state: "connected",
    syncState: "unavailable",
  });
  assert.equal(calls[0][0], "http://127.0.0.1:61555/v1/moomoo/status");
  assert.equal(
    (calls[0][1].headers as Record<string, string>).Authorization,
    `Bearer ${"x".repeat(43)}`,
  );
  assert.equal(calls[0][1].cache, "no-store");
});

test("desktop status explains rejected write scope without exposing returned scopes", async () => {
  const status = await loadMoomooDesktopStatus(
    desktopEnvironment,
    async () =>
      Response.json({
        account_count: 0,
        capabilities: [],
        error_code: "moomoo_write_scope_not_permitted",
        position_count: 0,
        state: "failed",
        sync_state: "failed",
      }),
  );

  assert.equal(
    status.detail,
    "Moomoo returned write access. Turn off Select all, Watchlists, and Trade Execution; keep only required read access, then reconnect.",
  );
  assert.doesNotMatch(status.detail, /trade:write/);
});

test("desktop status explains when silent restoration needs browser authorization", async () => {
  const status = await loadMoomooDesktopStatus(
    desktopEnvironment,
    async () =>
      Response.json({
        account_count: 0,
        capabilities: [],
        error_code: "moomoo_saved_authorization_unavailable",
        position_count: 0,
        state: "failed",
        sync_state: "failed",
      }),
  );

  assert.equal(
    status.detail,
    "Saved Moomoo authorization expired or was revoked. Connect once in browser to restore it.",
  );
});

test("connect sends authenticated operator identity and exact registered redirect", async () => {
  const calls: Array<[string, RequestInit]> = [];

  const result = await beginMoomooDesktopConnection(
    {
      clientId: "4a8bcd69-e915-4778-9583-17ad0e9e6a80",
      operatorId: "11111111-1111-4111-8111-111111111111",
    },
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json(
        {
          account_count: 0,
          capabilities: [],
          error_code: null,
          position_count: 0,
          state: "pending",
          sync_state: "pending",
        },
        { status: 202 },
      );
    },
  );

  assert.equal(result.state, "pending");
  assert.equal(calls[0][0], "http://127.0.0.1:61555/v1/moomoo/connect");
  assert.equal(calls[0][1].method, "POST");
  assert.deepEqual(JSON.parse(String(calls[0][1].body)), {
    client_id: "4a8bcd69-e915-4778-9583-17ad0e9e6a80",
    operator_id: "11111111-1111-4111-8111-111111111111",
    redirect_uri: "http://127.0.0.1:60355/callback",
  });
});

test("connect rejects invalid client identity before worker request", async () => {
  await assert.rejects(
    () =>
      beginMoomooDesktopConnection(
        {
          clientId: "not-a-client-id",
          operatorId: "11111111-1111-4111-8111-111111111111",
        },
        desktopEnvironment,
        async () => {
          throw new Error("must not fetch");
        },
      ),
    { message: "Moomoo connection request is invalid" },
  );
});

test("resume exchanges saved Keychain authorization without browser redirect", async () => {
  const calls: Array<[string, RequestInit]> = [];

  const result = await resumeMoomooDesktopConnection(
    {
      clientId: "4a8bcd69-e915-4778-9583-17ad0e9e6a80",
      operatorId: "11111111-1111-4111-8111-111111111111",
    },
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json({
        account_count: 1,
        capabilities: ["market_data", "portfolio_holdings"],
        error_code: null,
        position_count: 1,
        state: "connected",
        sync_state: "ready",
      });
    },
  );

  assert.equal(result.state, "connected");
  assert.equal(calls[0][0], "http://127.0.0.1:61555/v1/moomoo/resume");
  assert.deepEqual(JSON.parse(String(calls[0][1].body)), {
    client_id: "4a8bcd69-e915-4778-9583-17ad0e9e6a80",
    operator_id: "11111111-1111-4111-8111-111111111111",
  });
});

test("manual refresh sends only authenticated operator identity", async () => {
  const calls: Array<[string, RequestInit]> = [];

  const status = await refreshMoomooDesktopHoldings(
    { operatorId: "11111111-1111-4111-8111-111111111111" },
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json({
        account_count: 1,
        capabilities: ["market_data", "portfolio_holdings"],
        error_code: null,
        position_count: 1,
        state: "connected",
        sync_state: "ready",
      });
    },
  );

  assert.equal(status.syncState, "ready");
  assert.equal(calls[0][0], "http://127.0.0.1:61555/v1/moomoo/refresh");
  assert.deepEqual(JSON.parse(String(calls[0][1].body)), {
    operator_id: "11111111-1111-4111-8111-111111111111",
  });
});

test("disconnect clears only local app authorization state", async () => {
  const calls: Array<[string, RequestInit]> = [];

  const status = await disconnectMoomooDesktop(
    { operatorId: "11111111-1111-4111-8111-111111111111" },
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json({
        account_count: 0,
        capabilities: [],
        error_code: null,
        position_count: 0,
        state: "disconnected",
        sync_state: "unavailable",
      });
    },
  );

  assert.equal(status.state, "disconnected");
  assert.equal(calls[0][0], "http://127.0.0.1:61555/v1/moomoo/disconnect");
  assert.deepEqual(JSON.parse(String(calls[0][1].body)), {
    operator_id: "11111111-1111-4111-8111-111111111111",
  });
});

test("compose sends owner and canonical security candidates to local worker", async () => {
  const calls: Array<[string, RequestInit]> = [];
  const result = await composeMoomooDesktopSnapshots(
    {
      checkedAt: new Date("2026-08-13T09:31:00Z"),
      operatorId: "11111111-1111-4111-8111-111111111111",
      candidates: [
        {
          primaryListingExchange: "NASDAQ",
          securityId: "22222222-2222-4222-8222-222222222222",
          ticker: "GANX",
        },
      ],
    },
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json({ snapshot_count: 0, snapshots: [] });
    },
  );

  assert.deepEqual(result, { snapshot_count: 0, snapshots: [] });
  assert.equal(calls[0][0], "http://127.0.0.1:61555/v1/moomoo/compose");
  assert.deepEqual(JSON.parse(String(calls[0][1].body)), {
    candidates: [
      {
        primary_listing_exchange: "NASDAQ",
        security_id: "22222222-2222-4222-8222-222222222222",
        ticker: "GANX",
      },
    ],
    checked_at: "2026-08-13T09:31:00.000Z",
    operator_id: "11111111-1111-4111-8111-111111111111",
  });
});

test("desktop holdings remain decimal strings from worker to dashboard", async () => {
  const holdings = await loadMoomooDesktopHoldings(
    desktopEnvironment,
    async () =>
      Response.json({
        account_count: 1,
        position_count: 1,
        positions: [
          {
            account_index: 1,
            code: "US.GANX",
            cost_price: "1.7200",
            cost_price_valid: true,
            currency: "USD",
            market_val: "184.0000",
            nominal_price: "1.8400",
            pl_val: "12.0000",
            pl_val_valid: true,
            position_side: "LONG",
            qty: "100.0000",
            stock_name: "Gain Therapeutics",
          },
        ],
        sync_state: "ready",
      }),
  );

  assert.equal(holdings?.positions[0].quantity, "100.0000");
  assert.equal(holdings?.positions[0].marketValue, "184.0000");
  assert.equal(typeof holdings?.positions[0].marketValue, "string");
});

test("live quotes remain timestamped decimal strings from local worker", async () => {
  const stream = await loadMoomooDesktopQuotes(
    desktopEnvironment,
    async () => Response.json({
      error_code: null,
      quotes: [{
        data_time_ms: 1786590000123,
        high_price: "3.12",
        last_price: "3.07",
        low_price: "2.95",
        open_price: "3",
        previous_close_price: "3.01",
        security_status: "NORMAL",
        suspension: false,
        symbol: "US.RXRX",
        turnover: "378901.25",
        volume: "123456",
      }],
      state: "connected",
      symbols: ["US.RXRX"],
    }),
  );

  assert.equal(stream?.quotes[0].lastPrice, "3.07");
  assert.equal(stream?.quotes[0].dataTimeMs, 1786590000123);
});

test("subscription replacement batches selected symbols in one local command", async () => {
  const calls: Array<[string, RequestInit]> = [];
  const result = await replaceMoomooDesktopQuoteSubscriptions(
    {
      operatorId: "11111111-1111-4111-8111-111111111111",
      symbols: ["US.RXRX", "US.GANX"],
    },
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json({
        error_code: null,
        quotes: [],
        state: "connected",
        symbols: ["US.GANX", "US.RXRX"],
      });
    },
  );

  assert.deepEqual(result.symbols, ["US.GANX", "US.RXRX"]);
  assert.equal(
    calls[0][0],
    "http://127.0.0.1:61555/v1/moomoo/quotes/subscriptions",
  );
  assert.deepEqual(JSON.parse(String(calls[0][1].body)), {
    operator_id: "11111111-1111-4111-8111-111111111111",
    symbols: ["US.RXRX", "US.GANX"],
  });
});
