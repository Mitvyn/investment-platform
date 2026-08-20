import {
  isMoomooComposition,
  type MoomooComposition,
} from "./portfolio-persistence.ts";

type DesktopEnvironment = Record<string, string | undefined>;
type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export const MOOMOO_DESKTOP_CALLBACK_URL =
  "http://127.0.0.1:60355/callback";

type WorkerStatus = {
  account_count: number;
  capabilities: Array<"market_data" | "portfolio_holdings">;
  error_code: string | null;
  position_count: number;
  state: "connected" | "disconnected" | "disconnecting" | "failed" | "pending";
  sync_state: "failed" | "pending" | "ready" | "unavailable";
};

export type MoomooDesktopStatus = {
  accountCount: number;
  canReadMarketData: boolean;
  canReadPortfolio: boolean;
  detail: string;
  positionCount: number;
  state: "connected" | "disconnected" | "failed" | "pending" | "unavailable";
  syncState: "failed" | "pending" | "ready" | "unavailable";
};

export type MoomooCapabilityState = {
  detail: string;
  id: "market_data" | "portfolio_holdings" | "trade_execution";
  label: string;
  state: "enabled" | "not_supported" | "reconnect_required";
};

export function presentMoomooCapabilityStates(
  status: MoomooDesktopStatus,
): MoomooCapabilityState[] {
  const connected = status.state === "connected";
  const marketDataDetail = status.canReadMarketData
    ? "Live quotes available for selected security."
    : connected
      ? "Enable Market Data in Moomoo, then reconnect."
      : "Connect Moomoo, then enable Market Data.";
  const holdingsDetail = status.canReadPortfolio
    ? "Read-only holdings refresh and mirror save available."
    : connected
      ? "Enable Accounts & Orders for one account, then reconnect."
      : "Connect Moomoo and grant one account for holdings access.";
  return [
    {
      detail: marketDataDetail,
      id: "market_data",
      label: "Market data",
      state: status.canReadMarketData ? "enabled" : "reconnect_required",
    },
    {
      detail: holdingsDetail,
      id: "portfolio_holdings",
      label: "Holdings mirror",
      state: status.canReadPortfolio ? "enabled" : "reconnect_required",
    },
    {
      detail: "Not supported by this app. No order or trade-execution path exists.",
      id: "trade_execution",
      label: "Trade execution",
      state: "not_supported",
    },
  ];
}

export function describeMoomooError(errorCode: string) {
  if (errorCode === "persist_failed") {
    return "Moomoo holdings could not be saved. Live holdings remain unchanged.";
  }
  if (errorCode === "refresh_failed") {
    return "Moomoo holdings refresh failed. Existing mirror remains visible; reconnect if authorization expired.";
  }
  if (errorCode === "disconnect_failed") {
    return "Local disconnect did not finish. Retry before reconnecting so any live quote stream stays app-owned.";
  }
  if (errorCode === "quote_failed") {
    return "Live Moomoo quote could not start. Existing daily market context remains available.";
  }
  if (errorCode === "moomoo_saved_authorization_unavailable") {
    return "Saved Moomoo authorization expired or was revoked. Connect once in browser to restore it.";
  }
  if (errorCode === "moomoo_missing_required_read_scope") {
    return "Moomoo did not grant both required read scopes. Select Market Data and Accounts & Orders, then reconnect.";
  }
  if (
    errorCode === "moomoo_concrete_account_scope_missing" ||
    errorCode === "moomoo_wildcard_account_scope_not_permitted"
  ) {
    return "Moomoo did not bind authorization to a concrete trading account. Select your account under Accounts & Orders, then reconnect.";
  }
  if (errorCode === "moomoo_write_scope_not_permitted") {
    return "Moomoo returned write access. Turn off Select all, Watchlists, and Trade Execution; keep only required read access, then reconnect.";
  }
  if (errorCode === "moomoo_unknown_scope_not_permitted") {
    return "Moomoo returned an unsupported permission. Reconnect with only Market Data and read-only Accounts & Orders access.";
  }
  return "Moomoo connection could not start. Check client ID, exact registered callback URL, and desktop worker status.";
}

export type MoomooDesktopPosition = {
  accountIndex: number;
  code: string;
  costPrice: string | null;
  costPriceValid: boolean;
  currency: string;
  marketValue: string;
  nominalPrice: string;
  plValue: string | null;
  plValueValid: boolean;
  positionSide: string;
  quantity: string;
  stockName: string;
  canonicalTicker?: string;
  mappingState?: "mapped" | "unmapped" | "ambiguous";
  securityId?: string | null;
};

export type MoomooDesktopHoldings = {
  accountCount: number;
  positionCount: number;
  positions: MoomooDesktopPosition[];
  source: "desktop_live" | "hosted_snapshot";
  checkedAt?: string;
};

type WorkerQuoteStream = {
  error_code: string | null;
  quotes: Array<{
    data_time_ms: number;
    high_price: string | null;
    last_price: string | null;
    low_price: string | null;
    open_price: string | null;
    previous_close_price: string | null;
    security_status: string | null;
    suspension: boolean | null;
    symbol: string;
    turnover: string | null;
    volume: string | null;
  }>;
  state:
    | "blocked"
    | "connected"
    | "connecting"
    | "disconnected"
    | "quota_blocked"
    | "reconnecting"
    | "unavailable";
  symbols: string[];
};

export type MoomooDesktopQuoteStream = {
  errorCode: string | null;
  quotes: Array<{
    dataTimeMs: number;
    highPrice: string | null;
    lastPrice: string | null;
    lowPrice: string | null;
    openPrice: string | null;
    previousClosePrice: string | null;
    securityStatus: string | null;
    suspension: boolean | null;
    symbol: string;
    turnover: string | null;
    volume: string | null;
  }>;
  state: WorkerQuoteStream["state"];
  symbols: string[];
};

type WorkerHoldings = {
  account_count: number;
  position_count: number;
  positions: Array<{
    account_index: number;
    code: string;
    cost_price: string | null;
    cost_price_valid: boolean;
    currency: string;
    market_val: string;
    nominal_price: string;
    pl_val: string | null;
    pl_val_valid: boolean;
    position_side: string;
    qty: string;
    stock_name: string;
  }>;
  sync_state: "ready" | "unavailable";
};

export type BeginMoomooConnectionInput = {
  clientId: string;
  operatorId: string;
};

export type MoomooOperatorCommandInput = {
  operatorId: string;
};

export type ReplaceMoomooQuoteSubscriptionsInput = MoomooOperatorCommandInput & {
  symbols: string[];
};

export type ComposeMoomooSnapshotsInput = {
  candidates: Array<{
    primaryListingExchange: string;
    securityId: string;
    ticker: string;
  }>;
  checkedAt: Date;
  operatorId: string;
};

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CONTROL_ORIGIN_PATTERN = /^http:\/\/127\.0\.0\.1:\d+$/;
const DECIMAL_PATTERN = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const MOOMOO_SYMBOL_PATTERN = /^[A-Z]{2,3}\.[A-Z0-9][A-Z0-9.\-]{0,31}$/;

function controlContract(environment: DesktopEnvironment) {
  const origin = environment.IROS_DESKTOP_CONTROL_ORIGIN ?? "";
  const token = environment.IROS_DESKTOP_CONTROL_TOKEN ?? "";
  if (
    environment.IROS_DESKTOP !== "1" ||
    environment.IROS_DESKTOP_WORKER_STATE !== "ready" ||
    !CONTROL_ORIGIN_PATTERN.test(origin) ||
    token.length < 32
  ) {
    return null;
  }
  return { origin, token };
}

function isWorkerStatus(value: unknown): value is WorkerStatus {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<WorkerStatus>;
  return (
    ["connected", "disconnected", "disconnecting", "failed", "pending"].includes(
      String(candidate.state),
    ) &&
    Number.isInteger(candidate.account_count) &&
    Number(candidate.account_count) >= 0 &&
    Array.isArray(candidate.capabilities) &&
    new Set(candidate.capabilities).size === candidate.capabilities.length &&
    candidate.capabilities.every((capability) =>
      ["market_data", "portfolio_holdings"].includes(String(capability))
    ) &&
    Number.isInteger(candidate.position_count) &&
    Number(candidate.position_count) >= 0 &&
    ["failed", "pending", "ready", "unavailable"].includes(
      String(candidate.sync_state),
    ) &&
    (candidate.error_code === null || typeof candidate.error_code === "string")
  );
}

function presentStatus(status: WorkerStatus): MoomooDesktopStatus {
  if (status.state === "connected") {
    return {
      accountCount: status.account_count,
      canReadMarketData: status.capabilities.includes("market_data"),
      canReadPortfolio: status.capabilities.includes("portfolio_holdings"),
      detail: connectedDetail(status),
      positionCount: status.position_count,
      state: "connected",
      syncState: status.sync_state,
    };
  }
  if (status.state === "pending" || status.state === "disconnecting") {
    return {
      accountCount: 0,
      canReadMarketData: false,
      canReadPortfolio: false,
      detail:
        status.state === "disconnecting"
          ? "Disconnecting Moomoo"
          : "Finish authorization in system browser",
      positionCount: 0,
      state: "pending",
      syncState: "pending",
    };
  }
  if (status.state === "failed") {
    return {
      accountCount: 0,
      canReadMarketData: false,
      canReadPortfolio: false,
      detail: status.error_code
        ? describeMoomooError(status.error_code)
        : "Moomoo authorization failed",
      positionCount: 0,
      state: "failed",
      syncState: "failed",
    };
  }
  return {
    accountCount: 0,
    canReadMarketData: false,
    canReadPortfolio: false,
    detail: "Moomoo read-only authorization not connected",
    positionCount: 0,
    state: "disconnected",
    syncState: "unavailable",
  };
}

function connectedDetail(status: WorkerStatus) {
  if (status.sync_state === "ready") {
    const positionLabel = status.position_count === 1 ? "position" : "positions";
    const accountLabel = status.account_count === 1 ? "account" : "accounts";
    return `${status.position_count} ${positionLabel} synced from ${status.account_count} ${accountLabel}`;
  }
  if (status.sync_state === "failed") {
    return `Authorization connected; ${status.error_code ?? "holdings sync failed"}`;
  }
  if (
    status.capabilities.includes("market_data") &&
    !status.capabilities.includes("portfolio_holdings")
  ) {
    return "Market data connected; holdings unavailable without Accounts & Orders access";
  }
  if (
    status.capabilities.includes("portfolio_holdings") &&
    !status.capabilities.includes("market_data")
  ) {
    return "Holdings access connected; market data unavailable";
  }
  if (status.capabilities.length === 0) {
    return "Authorization connected; no supported read capability was granted";
  }
  return "Read-only authorization connected; account discovery pending";
}

function isWorkerHoldings(value: unknown): value is WorkerHoldings {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<WorkerHoldings>;
  if (
    !Number.isInteger(candidate.account_count) ||
    Number(candidate.account_count) < 0 ||
    !Number.isInteger(candidate.position_count) ||
    Number(candidate.position_count) < 0 ||
    !Array.isArray(candidate.positions) ||
    !["ready", "unavailable"].includes(String(candidate.sync_state)) ||
    candidate.positions.length !== candidate.position_count
  ) return false;
  return candidate.positions.every((position) => {
    if (!position || typeof position !== "object") return false;
    const requiredText = [
      position.code,
      position.currency,
      position.position_side,
      position.stock_name,
    ];
    return Number.isInteger(position.account_index) && position.account_index > 0 &&
      requiredText.every((item) => typeof item === "string" && item.length > 0) &&
      [position.qty, position.nominal_price, position.market_val].every(
        (item) => typeof item === "string" && DECIMAL_PATTERN.test(item),
      ) &&
      typeof position.cost_price_valid === "boolean" &&
      typeof position.pl_val_valid === "boolean" &&
      (position.cost_price === null ||
        (typeof position.cost_price === "string" && DECIMAL_PATTERN.test(position.cost_price))) &&
      (position.pl_val === null ||
        (typeof position.pl_val === "string" && DECIMAL_PATTERN.test(position.pl_val)));
  });
}

function isWorkerQuoteStream(value: unknown): value is WorkerQuoteStream {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<WorkerQuoteStream>;
  if (
    ![
      "blocked",
      "connected",
      "connecting",
      "disconnected",
      "quota_blocked",
      "reconnecting",
      "unavailable",
    ]
      .includes(String(candidate.state)) ||
    !Array.isArray(candidate.symbols) ||
    candidate.symbols.length > 25 ||
    new Set(candidate.symbols).size !== candidate.symbols.length ||
    candidate.symbols.some((symbol) =>
      typeof symbol !== "string" || !MOOMOO_SYMBOL_PATTERN.test(symbol)
    ) ||
    !Array.isArray(candidate.quotes) ||
    (candidate.error_code !== null && typeof candidate.error_code !== "string")
  ) return false;
  return candidate.quotes.every((quote) => {
    if (!quote || typeof quote !== "object") return false;
    const decimals = [
      quote.high_price,
      quote.last_price,
      quote.low_price,
      quote.open_price,
      quote.previous_close_price,
      quote.turnover,
      quote.volume,
    ];
    return MOOMOO_SYMBOL_PATTERN.test(quote.symbol) &&
      candidate.symbols?.includes(quote.symbol) === true &&
      Number.isSafeInteger(quote.data_time_ms) && quote.data_time_ms > 0 &&
      decimals.every((item) =>
        item === null || (typeof item === "string" && DECIMAL_PATTERN.test(item))
      ) &&
      (quote.security_status === null || typeof quote.security_status === "string") &&
      (quote.suspension === null || typeof quote.suspension === "boolean");
  });
}

function presentQuoteStream(stream: WorkerQuoteStream): MoomooDesktopQuoteStream {
  return {
    errorCode: stream.error_code,
    quotes: stream.quotes.map((quote) => ({
      dataTimeMs: quote.data_time_ms,
      highPrice: quote.high_price,
      lastPrice: quote.last_price,
      lowPrice: quote.low_price,
      openPrice: quote.open_price,
      previousClosePrice: quote.previous_close_price,
      securityStatus: quote.security_status,
      suspension: quote.suspension,
      symbol: quote.symbol,
      turnover: quote.turnover,
      volume: quote.volume,
    })),
    state: stream.state,
    symbols: stream.symbols,
  };
}

async function readResponse(response: Response): Promise<WorkerStatus> {
  const payload: unknown = await response.json();
  if (!response.ok || !isWorkerStatus(payload)) {
    throw new Error("Desktop Moomoo worker returned an invalid response");
  }
  return payload;
}

export async function loadMoomooDesktopStatus(
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<MoomooDesktopStatus> {
  const contract = controlContract(environment);
  if (!contract) {
    return {
      accountCount: 0,
      canReadMarketData: false,
      canReadPortfolio: false,
      detail: "Open desktop app to connect Moomoo",
      positionCount: 0,
      state: "unavailable",
      syncState: "unavailable",
    };
  }
  try {
    const response = await fetcher(`${contract.origin}/v1/moomoo/status`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${contract.token}` },
      signal: AbortSignal.timeout(3_000),
    });
    return presentStatus(await readResponse(response));
  } catch {
    return {
      accountCount: 0,
      canReadMarketData: false,
      canReadPortfolio: false,
      detail: "Local Moomoo connection service unavailable",
      positionCount: 0,
      state: "failed",
      syncState: "failed",
    };
  }
}

export async function loadMoomooDesktopHoldings(
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<MoomooDesktopHoldings | null> {
  const contract = controlContract(environment);
  if (!contract) return null;
  try {
    const response = await fetcher(`${contract.origin}/v1/moomoo/holdings`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${contract.token}` },
      signal: AbortSignal.timeout(3_000),
    });
    const payload: unknown = await response.json();
    if (!response.ok || !isWorkerHoldings(payload) || payload.sync_state !== "ready") {
      return null;
    }
    return {
      accountCount: payload.account_count,
      positionCount: payload.position_count,
      positions: payload.positions.map((position) => ({
        accountIndex: position.account_index,
        code: position.code,
        costPrice: position.cost_price,
        costPriceValid: position.cost_price_valid,
        currency: position.currency,
        marketValue: position.market_val,
        nominalPrice: position.nominal_price,
        plValue: position.pl_val,
        plValueValid: position.pl_val_valid,
        positionSide: position.position_side,
        quantity: position.qty,
        stockName: position.stock_name,
      })),
      source: "desktop_live",
    };
  } catch {
    return null;
  }
}

export async function loadMoomooDesktopQuotes(
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<MoomooDesktopQuoteStream | null> {
  const contract = controlContract(environment);
  if (!contract) return null;
  try {
    const response = await fetcher(`${contract.origin}/v1/moomoo/quotes`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${contract.token}` },
      signal: AbortSignal.timeout(3_000),
    });
    const payload: unknown = await response.json();
    if (!response.ok || !isWorkerQuoteStream(payload)) return null;
    return presentQuoteStream(payload);
  } catch {
    return null;
  }
}

export async function replaceMoomooDesktopQuoteSubscriptions(
  input: ReplaceMoomooQuoteSubscriptionsInput,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<MoomooDesktopQuoteStream> {
  const contract = controlContract(environment);
  if (
    !contract ||
    !UUID_PATTERN.test(input.operatorId) ||
    input.symbols.length > 25 ||
    input.symbols.some((symbol) => !MOOMOO_SYMBOL_PATTERN.test(symbol))
  ) {
    throw new Error("Moomoo quote subscription request is invalid");
  }
  const response = await fetcher(
    `${contract.origin}/v1/moomoo/quotes/subscriptions`,
    {
      body: JSON.stringify({
        operator_id: input.operatorId,
        symbols: input.symbols,
      }),
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${contract.token}`,
        "Content-Type": "application/json",
      },
      method: "POST",
      signal: AbortSignal.timeout(3_000),
    },
  );
  const payload: unknown = await response.json();
  if (!response.ok || !isWorkerQuoteStream(payload)) {
    throw new Error("Desktop Moomoo quote worker returned an invalid response");
  }
  return presentQuoteStream(payload);
}

export async function beginMoomooDesktopConnection(
  input: BeginMoomooConnectionInput,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<MoomooDesktopStatus> {
  const contract = controlContract(environment);
  if (
    !contract ||
    !UUID_PATTERN.test(input.clientId) ||
    !UUID_PATTERN.test(input.operatorId)
  ) {
    throw new Error("Moomoo connection request is invalid");
  }
  const response = await fetcher(`${contract.origin}/v1/moomoo/connect`, {
    body: JSON.stringify({
      client_id: input.clientId,
      operator_id: input.operatorId,
      redirect_uri: MOOMOO_DESKTOP_CALLBACK_URL,
    }),
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${contract.token}`,
      "Content-Type": "application/json",
    },
    method: "POST",
    signal: AbortSignal.timeout(3_000),
  });
  return presentStatus(await readResponse(response));
}

export async function resumeMoomooDesktopConnection(
  input: BeginMoomooConnectionInput,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<MoomooDesktopStatus> {
  const contract = controlContract(environment);
  if (
    !contract ||
    !UUID_PATTERN.test(input.clientId) ||
    !UUID_PATTERN.test(input.operatorId)
  ) {
    throw new Error("Moomoo resume request is invalid");
  }
  const response = await fetcher(`${contract.origin}/v1/moomoo/resume`, {
    body: JSON.stringify({
      client_id: input.clientId,
      operator_id: input.operatorId,
    }),
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${contract.token}`,
      "Content-Type": "application/json",
    },
    method: "POST",
    signal: AbortSignal.timeout(10_000),
  });
  return presentStatus(await readResponse(response));
}

export async function refreshMoomooDesktopHoldings(
  input: MoomooOperatorCommandInput,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<MoomooDesktopStatus> {
  const contract = controlContract(environment);
  if (!contract || !UUID_PATTERN.test(input.operatorId)) {
    throw new Error("Moomoo refresh request is invalid");
  }
  const response = await fetcher(`${contract.origin}/v1/moomoo/refresh`, {
    body: JSON.stringify({ operator_id: input.operatorId }),
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${contract.token}`,
      "Content-Type": "application/json",
    },
    method: "POST",
    signal: AbortSignal.timeout(10_000),
  });
  return presentStatus(await readResponse(response));
}

export async function disconnectMoomooDesktop(
  input: MoomooOperatorCommandInput,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<MoomooDesktopStatus> {
  const contract = controlContract(environment);
  if (!contract || !UUID_PATTERN.test(input.operatorId)) {
    throw new Error("Moomoo disconnect request is invalid");
  }
  const response = await fetcher(`${contract.origin}/v1/moomoo/disconnect`, {
    body: JSON.stringify({ operator_id: input.operatorId }),
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${contract.token}`,
      "Content-Type": "application/json",
    },
    method: "POST",
    signal: AbortSignal.timeout(3_000),
  });
  return presentStatus(await readResponse(response));
}

export async function composeMoomooDesktopSnapshots(
  input: ComposeMoomooSnapshotsInput,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<MoomooComposition> {
  const contract = controlContract(environment);
  if (
    !contract ||
    !UUID_PATTERN.test(input.operatorId) ||
    !Number.isFinite(input.checkedAt.getTime()) ||
    input.candidates.length > 100 ||
    input.candidates.some(
      (candidate) =>
        !UUID_PATTERN.test(candidate.securityId) ||
        !candidate.ticker.trim() ||
        !candidate.primaryListingExchange.trim(),
    )
  ) {
    throw new Error("Moomoo compose request is invalid");
  }
  const response = await fetcher(`${contract.origin}/v1/moomoo/compose`, {
    body: JSON.stringify({
      candidates: input.candidates.map((candidate) => ({
        primary_listing_exchange: candidate.primaryListingExchange,
        security_id: candidate.securityId,
        ticker: candidate.ticker,
      })),
      checked_at: input.checkedAt.toISOString(),
      operator_id: input.operatorId,
    }),
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${contract.token}`,
      "Content-Type": "application/json",
    },
    method: "POST",
    signal: AbortSignal.timeout(10_000),
  });
  const payload: unknown = await response.json();
  if (!response.ok || !isMoomooComposition(payload)) {
    throw new Error("Desktop Moomoo worker returned an invalid composition");
  }
  return payload;
}
