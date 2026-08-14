import { createHash } from "node:crypto";

const RPC_NAME = "iros_persist_portfolio_broker_snapshot";
const TRACE_NAMESPACE = "791c6c1a-c93f-4b41-889e-7e48032c9d70";
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;

type MappingState = "mapped" | "unmapped" | "ambiguous";

export type MoomooComposedPosition = {
  available_quantity: string;
  average_cost: string | null;
  average_cost_state: "reported" | "provider_invalid";
  canonical_ticker: string;
  currency: string;
  display_name: string;
  last_price: string;
  mapping_state: MappingState;
  market_value: string;
  ordinal: number;
  position_id: string;
  position_side: string;
  precision_risk_fields: string[];
  primary_listing_exchange: string | null;
  provider_symbol: string;
  quantity: string;
  security_id: string | null;
  snapshot_id: string;
  unrealized_pnl: string | null;
  unrealized_pnl_state: "reported" | "provider_invalid";
};

export type MoomooComposedSnapshot = {
  account_ref: string;
  ambiguous_count: number;
  captured_at: string;
  content_sha256: string;
  contract_version: "portfolio_snapshot.v1";
  operator_id: string;
  position_count: number;
  positions: MoomooComposedPosition[];
  precision_risk_count: number;
  provider: "moomoo_rest" | "moomoo_opend";
  provider_transport: "web_rest_oauth" | "opend_local_tcp";
  read_only_assurance: "read_only_scopes_no_order_surface";
  snapshot_id: string;
  unmapped_count: number;
};

export type MoomooComposition = {
  snapshot_count: number;
  snapshots: Array<{
    account_label: string;
    account_type: string;
    security_firm: string;
    snapshot: MoomooComposedSnapshot;
  }>;
};

export function isMoomooComposition(value: unknown): value is MoomooComposition {
  if (!value || typeof value !== "object") return false;
  const composition = value as Partial<MoomooComposition>;
  if (
    !Number.isInteger(composition.snapshot_count) ||
    Number(composition.snapshot_count) < 0 ||
    !Array.isArray(composition.snapshots) ||
    composition.snapshots.length !== composition.snapshot_count
  ) return false;
  return composition.snapshots.every((item) => {
    if (!item || typeof item !== "object") return false;
    const snapshot = item.snapshot;
    return (
      typeof item.account_label === "string" &&
      typeof item.account_type === "string" &&
      typeof item.security_firm === "string" &&
      isComposedSnapshot(snapshot)
    );
  });
}

export type PortfolioPersistenceReceipt = {
  account_ref: string;
  checked_at: string;
  idempotency_key: string;
  outcome: "created" | "already_present";
  receipt_id: string;
  request_sha256: string;
  snapshot_id: string;
  sync_state: "complete";
};

type RpcResult = {
  data: unknown;
  error: unknown;
};

type Rpc = (
  name: string,
  parameters: Record<string, unknown>,
) => Promise<RpcResult>;

export class PortfolioPersistenceError extends Error {
  readonly code: "persist_failed";

  constructor() {
    super("persist_failed");
    this.name = "PortfolioPersistenceError";
    this.code = "persist_failed";
  }
}

export async function persistMoomooPortfolioMirror(input: {
  operatorId: string;
  checkedAt: Date;
  composition: MoomooComposition;
  rpc: Rpc;
}): Promise<PortfolioPersistenceReceipt[]> {
  if (
    !UUID_PATTERN.test(input.operatorId) ||
    !Number.isFinite(input.checkedAt.getTime()) ||
    input.composition.snapshot_count !== input.composition.snapshots.length
  ) {
    throw new PortfolioPersistenceError();
  }
  const receipts: PortfolioPersistenceReceipt[] = [];
  for (const composed of input.composition.snapshots) {
    const parameters = buildRpcParameters(
      input.operatorId,
      composed,
      input.checkedAt,
    );
    const result = await input.rpc(RPC_NAME, parameters);
    if (result.error || !isReceipt(result.data, parameters)) {
      throw new PortfolioPersistenceError();
    }
    receipts.push(result.data);
  }
  return receipts;
}

function buildRpcParameters(
  operatorId: string,
  composed: MoomooComposition["snapshots"][number],
  checkedAt: Date,
): Record<string, unknown> {
  const snapshot = composed.snapshot;
  if (
    snapshot.operator_id !== operatorId ||
    !UUID_PATTERN.test(snapshot.account_ref) ||
    !UUID_PATTERN.test(snapshot.snapshot_id) ||
    !SHA256_PATTERN.test(snapshot.content_sha256) ||
    snapshot.position_count !== snapshot.positions.length ||
    Date.parse(snapshot.captured_at) > checkedAt.getTime()
  ) {
    throw new PortfolioPersistenceError();
  }
  const positions = snapshot.positions.map((position, index) => {
    if (
      position.ordinal !== index + 1 ||
      position.snapshot_id !== snapshot.snapshot_id ||
      !UUID_PATTERN.test(position.position_id) ||
      (position.security_id !== null && !UUID_PATTERN.test(position.security_id))
    ) {
      throw new PortfolioPersistenceError();
    }
    return {
      available_quantity: position.available_quantity,
      average_cost: position.average_cost,
      average_cost_state: position.average_cost_state,
      canonical_ticker: position.canonical_ticker,
      currency: position.currency,
      display_name: position.display_name,
      last_price: position.last_price,
      mapping_state: position.mapping_state,
      market_value: position.market_value,
      position_side: position.position_side,
      precision_risk_fields: position.precision_risk_fields,
      primary_listing_exchange: position.primary_listing_exchange,
      provider_symbol: position.provider_symbol,
      quantity: position.quantity,
      security_id: position.security_id,
      unrealized_pnl: position.unrealized_pnl,
      unrealized_pnl_state: position.unrealized_pnl_state,
    };
  });
  const account = {
    account_label: requiredText(composed.account_label),
    account_ref: snapshot.account_ref,
    account_type: requiredText(composed.account_type),
    provider: snapshot.provider,
    provider_transport: snapshot.provider_transport,
    security_firm: requiredText(composed.security_firm),
  };
  const snapshotPayload = {
    ambiguous_count: snapshot.ambiguous_count,
    captured_at: snapshot.captured_at,
    content_sha256: snapshot.content_sha256,
    contract_version: snapshot.contract_version,
    expected_position_count: snapshot.position_count,
    precision_risk_count: snapshot.precision_risk_count,
    read_only_assurance: snapshot.read_only_assurance,
    snapshot_id: snapshot.snapshot_id,
    unmapped_count: snapshot.unmapped_count,
  };
  const contentHash = sha256({
    account_ref: snapshot.account_ref,
    contract_version: snapshot.contract_version,
    positions,
    provider: snapshot.provider,
    provider_transport: snapshot.provider_transport,
    read_only_assurance: snapshot.read_only_assurance,
  });
  const expectedSnapshotId = stableId(
    operatorId,
    "portfolio-snapshot",
    `${snapshot.account_ref}:${contentHash}`,
  );
  if (
    contentHash !== snapshot.content_sha256 ||
    expectedSnapshotId !== snapshot.snapshot_id
  ) {
    throw new PortfolioPersistenceError();
  }
  const idempotencyKey =
    `portfolio-save:${snapshot.content_sha256}:${snapshot.account_ref}`;
  const requestSha256 = sha256({
    account,
    idempotency_key: idempotencyKey,
    operator_id: operatorId,
    positions,
    snapshot: snapshotPayload,
  });
  return {
    p_account: account,
    p_checked_at: checkedAt.toISOString(),
    p_idempotency_key: idempotencyKey,
    p_operator_id: operatorId,
    p_positions: positions,
    p_request_sha256: requestSha256,
    p_snapshot: snapshotPayload,
  };
}

function stableId(operatorId: string, recordType: string, identity: string) {
  const namespace = Buffer.from(TRACE_NAMESPACE.replaceAll("-", ""), "hex");
  const digest = createHash("sha1")
    .update(namespace)
    .update(`${operatorId}:${recordType}:${identity}`, "utf8")
    .digest();
  digest[6] = (digest[6] & 0x0f) | 0x50;
  digest[8] = (digest[8] & 0x3f) | 0x80;
  const value = digest.subarray(0, 16).toString("hex");
  return [
    value.slice(0, 8),
    value.slice(8, 12),
    value.slice(12, 16),
    value.slice(16, 20),
    value.slice(20),
  ].join("-");
}

function sha256(value: unknown) {
  return createHash("sha256").update(canonicalJson(value), "utf8").digest("hex");
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
    .join(",")}}`;
}

function requiredText(value: string) {
  const normalized = value.trim();
  if (!normalized) throw new PortfolioPersistenceError();
  return normalized;
}

function isReceipt(
  value: unknown,
  parameters: Record<string, unknown>,
): value is PortfolioPersistenceReceipt {
  if (!value || typeof value !== "object") return false;
  const receipt = value as Partial<PortfolioPersistenceReceipt>;
  return (
    UUID_PATTERN.test(String(receipt.receipt_id)) &&
    receipt.account_ref ===
      (parameters.p_account as Record<string, unknown>).account_ref &&
    receipt.snapshot_id ===
      (parameters.p_snapshot as Record<string, unknown>).snapshot_id &&
    receipt.idempotency_key === parameters.p_idempotency_key &&
    receipt.request_sha256 === parameters.p_request_sha256 &&
    receipt.sync_state === "complete" &&
    ["created", "already_present"].includes(String(receipt.outcome)) &&
    typeof receipt.checked_at === "string"
  );
}

function isComposedSnapshot(value: unknown): value is MoomooComposedSnapshot {
  if (!value || typeof value !== "object") return false;
  const snapshot = value as Partial<MoomooComposedSnapshot>;
  if (
    !UUID_PATTERN.test(String(snapshot.operator_id)) ||
    !UUID_PATTERN.test(String(snapshot.account_ref)) ||
    !UUID_PATTERN.test(String(snapshot.snapshot_id)) ||
    !SHA256_PATTERN.test(String(snapshot.content_sha256)) ||
    snapshot.contract_version !== "portfolio_snapshot.v1" ||
    snapshot.read_only_assurance !== "read_only_scopes_no_order_surface" ||
    !["moomoo_rest", "moomoo_opend"].includes(String(snapshot.provider)) ||
    !["web_rest_oauth", "opend_local_tcp"].includes(
      String(snapshot.provider_transport),
    ) ||
    typeof snapshot.captured_at !== "string" ||
    !Number.isFinite(Date.parse(snapshot.captured_at)) ||
    !Array.isArray(snapshot.positions) ||
    !Number.isInteger(snapshot.position_count) ||
    snapshot.positions.length !== snapshot.position_count ||
    ![snapshot.unmapped_count, snapshot.ambiguous_count, snapshot.precision_risk_count]
      .every((count) => Number.isInteger(count) && Number(count) >= 0)
  ) return false;
  return snapshot.positions.every(isComposedPosition);
}

function isComposedPosition(value: unknown): value is MoomooComposedPosition {
  if (!value || typeof value !== "object") return false;
  const position = value as Partial<MoomooComposedPosition>;
  return (
    Number.isInteger(position.ordinal) &&
    Number(position.ordinal) > 0 &&
    UUID_PATTERN.test(String(position.position_id)) &&
    UUID_PATTERN.test(String(position.snapshot_id)) &&
    ["mapped", "unmapped", "ambiguous"].includes(String(position.mapping_state)) &&
    ["reported", "provider_invalid"].includes(String(position.average_cost_state)) &&
    ["reported", "provider_invalid"].includes(String(position.unrealized_pnl_state)) &&
    Array.isArray(position.precision_risk_fields) &&
    position.precision_risk_fields.every((item) => typeof item === "string") &&
    [
      position.available_quantity,
      position.canonical_ticker,
      position.currency,
      position.display_name,
      position.last_price,
      position.market_value,
      position.position_side,
      position.provider_symbol,
      position.quantity,
    ].every((item) => typeof item === "string" && item.length > 0) &&
    (position.average_cost === null || typeof position.average_cost === "string") &&
    (position.unrealized_pnl === null || typeof position.unrealized_pnl === "string") &&
    (position.security_id === null || UUID_PATTERN.test(String(position.security_id))) &&
    (position.primary_listing_exchange === null ||
      typeof position.primary_listing_exchange === "string")
  );
}
