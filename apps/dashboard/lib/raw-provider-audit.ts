export type RawProviderPayloadKind = "grader" | "synthesis";

type Claims = Record<string, unknown>;

type AuditRpcClient = {
  rpc(
    name: string,
    args: Record<string, string>,
  ): PromiseLike<{ data: unknown; error: { message: string } | null }>;
};

export type RawProviderAuditPayload = {
  contract_version: "raw_provider_audit_payload.v1";
  operator_id: string;
  research_run_id: string;
  payload_kind: RawProviderPayloadKind;
  payload_id: string;
  raw_payload_sha256: string;
  request_payload: Record<string, unknown>;
  response_payload: Record<string, unknown> | null;
  access_audit_event_id: string;
  accessed_at: string;
};

export function hasRawProviderAuditPermission(claims: Claims): boolean {
  if (typeof claims.sub !== "string" || claims.sub.length === 0) return false;
  const metadata = claims.app_metadata;
  if (metadata === null || typeof metadata !== "object") return false;
  const permissions = (metadata as Record<string, unknown>).iros_permissions;
  return (
    Array.isArray(permissions) && permissions.includes("raw_provider_audit")
  );
}

function requiredText(
  value: unknown,
  label: string,
): asserts value is string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`invalid ${label}`);
  }
}

function parsePayload(value: unknown): RawProviderAuditPayload {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("invalid raw provider audit response");
  }
  const payload = value as Record<string, unknown>;
  if (payload.contract_version !== "raw_provider_audit_payload.v1") {
    throw new Error("invalid raw provider audit contract");
  }
  for (const key of [
    "operator_id",
    "research_run_id",
    "payload_id",
    "raw_payload_sha256",
    "access_audit_event_id",
    "accessed_at",
  ]) {
    requiredText(payload[key], key);
  }
  if (payload.payload_kind !== "grader" && payload.payload_kind !== "synthesis") {
    throw new Error("invalid raw provider payload kind");
  }
  if (
    payload.request_payload === null ||
    typeof payload.request_payload !== "object" ||
    Array.isArray(payload.request_payload)
  ) {
    throw new Error("invalid raw provider request payload");
  }
  if (
    payload.response_payload !== null &&
    (typeof payload.response_payload !== "object" ||
      Array.isArray(payload.response_payload))
  ) {
    throw new Error("invalid raw provider response payload");
  }
  return payload as RawProviderAuditPayload;
}

export async function readRawProviderPayload(
  client: AuditRpcClient,
  claims: Claims,
  request: {
    researchRunId: string;
    payloadKind: RawProviderPayloadKind;
    payloadId: string;
  },
): Promise<RawProviderAuditPayload> {
  if (!hasRawProviderAuditPermission(claims)) {
    throw new Error("raw provider audit permission required");
  }
  const operatorId = claims.sub as string;
  const { data, error } = await client.rpc("iros_read_raw_provider_payload", {
    p_research_run_id: request.researchRunId,
    p_payload_kind: request.payloadKind,
    p_payload_id: request.payloadId,
  });
  if (error) throw new Error(`raw provider audit failed: ${error.message}`);
  const payload = parsePayload(data);
  if (payload.operator_id !== operatorId) {
    throw new Error("raw provider audit owner mismatch");
  }
  if (
    payload.research_run_id !== request.researchRunId ||
    payload.payload_kind !== request.payloadKind ||
    payload.payload_id !== request.payloadId
  ) {
    throw new Error("raw provider audit identity mismatch");
  }
  return payload;
}
