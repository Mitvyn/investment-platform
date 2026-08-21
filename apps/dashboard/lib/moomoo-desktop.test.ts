import assert from "node:assert/strict";
import test from "node:test";

import {
  beginMoomooMcpAuthorization,
  beginMoomooDesktopConnection,
  composeMoomooDesktopSnapshots,
  disconnectMoomooDesktop,
  loadMoomooDesktopHoldings,
  loadDesktopSecurityRegistry,
  loadMoomooMcpDiscoveryStatus,
  loadMoomooDesktopQuotes,
  loadMoomooDesktopStatus,
  presentMoomooConnectionSummary,
  presentMoomooCapabilityStates,
  refreshMoomooDesktopHoldings,
  replaceMoomooDesktopQuoteSubscriptions,
  resumeMoomooDesktopConnection,
  discoverMoomooMcpTools,
  fetchMoomooMarketQuoteEvidence,
  loadMoomooMarketQuoteStatus,
  resumeMoomooMcpConnection,
  disconnectMoomooMcp,
  disconnectMoomooAll,
  loadMoomooDiagnostics,
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

test("capability matrix reports broker-returned connection capabilities without prescribing grants", () => {
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
        detail: "Broker returned market-data read capability for this connection.",
        id: "market_data",
        label: "Market data",
        state: "enabled",
      },
      {
        detail: "Broker did not return portfolio-read capability for this connection.",
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

test("desktop security registry loads local tickers without portfolio values", async () => {
  const entries = await loadDesktopSecurityRegistry(
    desktopEnvironment,
    async () =>
      Response.json({
        entries: [
          { sources: ["manual", "moomoo_position"], ticker: "RXRX" },
        ],
      }),
  );

  assert.deepEqual(entries, [
    { sources: ["manual", "moomoo_position"], ticker: "RXRX" },
  ]);
});

test("MCP discovery status stays server-owned and exposes metadata only", async () => {
  const calls: Array<[string, RequestInit]> = [];
  const status = await loadMoomooMcpDiscoveryStatus(
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json({
        error_code: null,
        state: "ready",
        tool_count: 1,
        tools: [
          {
            input_schema_sha256: "a".repeat(64),
            name: "quote_stock_quote",
          },
        ],
      });
    },
  );

  assert.deepEqual(status, {
    errorCode: null,
    state: "ready",
    toolCount: 1,
    tools: [
      {
        inputSchemaSha256: "a".repeat(64),
        name: "quote_stock_quote",
      },
    ],
  });
  assert.equal(calls[0][0], "http://127.0.0.1:61555/v1/moomoo/mcp/status");
  assert.equal(
    (calls[0][1].headers as Record<string, string>).Authorization,
    `Bearer ${"x".repeat(43)}`,
  );
});

test("MCP discovery sends only operator identity to local worker", async () => {
  const calls: Array<[string, RequestInit]> = [];
  const status = await discoverMoomooMcpTools(
    { operatorId: "11111111-1111-4111-8111-111111111111" },
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json({
        error_code: null,
        state: "ready",
        tool_count: 0,
        tools: [],
      });
    },
  );

  assert.equal(status.state, "ready");
  assert.equal(calls[0][0], "http://127.0.0.1:61555/v1/moomoo/mcp/discover");
  assert.deepEqual(JSON.parse(String(calls[0][1].body)), {
    operator_id: "11111111-1111-4111-8111-111111111111",
  });
});

test("MCP authorization starts through local worker with fixed callback only", async () => {
  const calls: Array<[string, RequestInit]> = [];
  const status = await beginMoomooMcpAuthorization(
    { operatorId: "11111111-1111-4111-8111-111111111111" },
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json(
        {
          error_code: null,
          state: "authorizing",
          tool_count: 0,
          tools: [],
        },
        { status: 202 },
      );
    },
  );

  assert.equal(status.state, "authorizing");
  assert.deepEqual(JSON.parse(String(calls[0][1].body)), {
    operator_id: "11111111-1111-4111-8111-111111111111",
    redirect_uri: "http://127.0.0.1:60355/callback",
  });
});

test("MCP resume sends only operator identity and reaches ready without a browser", async () => {
  const calls: Array<[string, RequestInit]> = [];
  const status = await resumeMoomooMcpConnection(
    { operatorId: "11111111-1111-4111-8111-111111111111" },
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json({ error_code: null, state: "ready", tool_count: 0, tools: [] });
    },
  );
  assert.equal(status.state, "ready");
  assert.equal(new URL(calls[0][0]).pathname, "/v1/moomoo/mcp/resume");
  assert.deepEqual(JSON.parse(String(calls[0][1].body)), {
    operator_id: "11111111-1111-4111-8111-111111111111",
  });
});

test("MCP resume fails closed to unavailable without a local desktop runtime", async () => {
  let called = false;
  const status = await resumeMoomooMcpConnection(
    { operatorId: "11111111-1111-4111-8111-111111111111" },
    {},
    async () => {
      called = true;
      throw new Error("must not fetch");
    },
  );
  assert.equal(called, false);
  assert.equal(status.state, "unavailable");
});

test("MCP disconnect clears only the core MCP connection", async () => {
  const calls: Array<[string, RequestInit]> = [];
  const status = await disconnectMoomooMcp(
    { operatorId: "11111111-1111-4111-8111-111111111111" },
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json({ error_code: null, state: "disconnected", tool_count: 0, tools: [] });
    },
  );
  assert.equal(status.state, "disconnected");
  assert.equal(new URL(calls[0][0]).pathname, "/v1/moomoo/mcp/disconnect");
});

test("disconnect-all posts an explicit combined action", async () => {
  const calls: Array<[string, RequestInit]> = [];
  await disconnectMoomooAll(
    { operatorId: "11111111-1111-4111-8111-111111111111" },
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return new Response(null, { status: 200 });
    },
  );
  assert.equal(new URL(calls[0][0]).pathname, "/v1/moomoo/disconnect-all");
});

test("diagnostics load only bounded safe fields and stay empty without a runtime", async () => {
  const unavailable = await loadMoomooDiagnostics({}, async () => {
    throw new Error("must not fetch");
  });
  assert.deepEqual(unavailable, []);

  const entries = await loadMoomooDiagnostics(desktopEnvironment, async () =>
    Response.json({
      contract_version: "moomoo_diagnostics.v1",
      entries: [
        {
          timestamp: "2026-08-21T12:00:00",
          subsystem: "core_mcp",
          stage: "ready",
          reason_code: "ok",
        },
        { timestamp: "2026-08-21T12:00:01", subsystem: "unexpected", stage: "x" },
      ],
    }),
  );
  assert.deepEqual(entries, [
    {
      timestamp: "2026-08-21T12:00:00",
      subsystem: "core_mcp",
      stage: "ready",
      reasonCode: "ok",
    },
  ]);
});

test("market quote evidence sends canonical identity and ticker to local worker", async () => {
  const calls: Array<[string, RequestInit]> = [];
  const status = await fetchMoomooMarketQuoteEvidence(
    {
      operatorId: "11111111-1111-4111-8111-111111111111",
      securityId: "22222222-2222-4222-8222-222222222222",
      ticker: "US.AAPL",
    },
    desktopEnvironment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json({
        cached: false,
        contract_version: "market_quote_evidence.v1",
        error_code: null,
        evidence: {
          failure_reason: null,
          freshness: "fresh",
          is_error: false,
          provider_reported_at: "2026-08-20T12:00:00+00:00",
          retrieved_at: "2026-08-20T12:00:00+00:00",
          security_id: "22222222-2222-4222-8222-222222222222",
          source: "moomoo_mcp",
          summary: { code: "US.AAPL" },
          ticker: "US.AAPL",
          tool_name: "quote_stock_quote",
        },
        state: "ready",
      });
    },
  );

  assert.equal(status.state, "ready");
  assert.equal(status.evidence?.ticker, "US.AAPL");
  assert.equal(calls[0][0], "http://127.0.0.1:61555/v1/research/market-evidence/quote");
  assert.deepEqual(JSON.parse(String(calls[0][1].body)), {
    operator_id: "11111111-1111-4111-8111-111111111111",
    security_id: "22222222-2222-4222-8222-222222222222",
    ticker: "US.AAPL",
  });
});

test("market quote evidence rejects invalid identity before any request", async () => {
  await assert.rejects(
    fetchMoomooMarketQuoteEvidence(
      { operatorId: "not-a-uuid", securityId: "22222222-2222-4222-8222-222222222222", ticker: "US.AAPL" },
      desktopEnvironment,
      async () => {
        throw new Error("must not fetch");
      },
    ),
  );
});

test("market quote evidence stays unavailable without local desktop runtime", async () => {
  const status = await fetchMoomooMarketQuoteEvidence(
    {
      operatorId: "11111111-1111-4111-8111-111111111111",
      securityId: "22222222-2222-4222-8222-222222222222",
      ticker: "US.AAPL",
    },
    {},
    async () => {
      throw new Error("must not fetch");
    },
  );
  assert.equal(status.state, "unavailable");
});

test("last market quote status loads via GET with only the security id", async () => {
  const calls: string[] = [];
  const status = await loadMoomooMarketQuoteStatus(
    "22222222-2222-4222-8222-222222222222",
    desktopEnvironment,
    async (url) => {
      calls.push(String(url));
      return Response.json({
        cached: true,
        contract_version: "market_quote_evidence.v1",
        error_code: null,
        evidence: null,
        state: "ready",
      });
    },
  );
  assert.equal(status.state, "ready");
  assert.equal(status.cached, true);
  assert.equal(
    calls[0],
    "http://127.0.0.1:61555/v1/research/market-evidence/quote?security_id=22222222-2222-4222-8222-222222222222",
  );
});

test("stale market quote status is surfaced distinctly, not as ready", async () => {
  const status = await loadMoomooMarketQuoteStatus(
    "22222222-2222-4222-8222-222222222222",
    desktopEnvironment,
    async () =>
      Response.json({
        cached: true,
        contract_version: "market_quote_evidence.v1",
        error_code: "moomoo_market_evidence_stale",
        evidence: null,
        state: "stale",
      }),
  );
  assert.equal(status.state, "stale");
  assert.notEqual(status.state, "ready");
});

test("last market quote status stays unavailable for an invalid security id without a request", async () => {
  const status = await loadMoomooMarketQuoteStatus(
    "not-a-uuid",
    desktopEnvironment,
    async () => {
      throw new Error("must not fetch");
    },
  );
  assert.equal(status.state, "unavailable");
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

test("desktop status retains generic detail if an older worker reports rejected write scope", async () => {
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
    "Moomoo connection needs a current desktop worker. Reopen preview app, then reconnect if needed.",
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
