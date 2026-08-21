export const MOOMOO_CLIENT_IDS_COOKIE = "iros_moomoo_client_ids_v1";
export const MOOMOO_AUTO_RESUME_COOKIE = "iros_moomoo_auto_resume_v1";
/**
 * Independent from `MOOMOO_AUTO_RESUME_COOKIE` (optional OpenAPI streaming).
 * Governs only the core MCP connection's silent startup resume: enabled by
 * a successful MCP authorization, disabled by an explicit MCP disconnect or
 * disconnect-all, and otherwise retained across ordinary relaunches.
 */
export const MOOMOO_MCP_AUTO_RESUME_COOKIE = "iros_moomoo_mcp_auto_resume_v1";

const MAX_SAVED_CLIENT_IDS = 5;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function parseMoomooClientIds(value: string | undefined): string[] {
  if (!value) return [];
  return uniqueValidIds(value.split(","));
}

export function parseMoomooAutoResumeClientId(
  value: string | undefined,
): string | null {
  if (!value || value === "disabled") return null;
  return parseMoomooClientIds(value)[0] ?? null;
}

/**
 * Absent means "never explicitly set" (a security scoped, not yet
 * authorized, connection) and is treated as disabled, matching every other
 * preference cookie in this module. Once authorization sets it "enabled",
 * an ordinary relaunch retains that value because the cookie is never
 * cleared or re-derived from anything else.
 */
export function isMoomooMcpAutoResumeEnabled(value: string | undefined): boolean {
  return value === "enabled";
}

export function serializeMoomooClientIds(values: readonly string[]): string {
  return uniqueValidIds(values).join(",");
}

export function addMoomooClientId(
  existing: readonly string[],
  clientId: string,
): string[] {
  const normalized = normalizeClientId(clientId);
  if (!normalized) throw new Error("moomoo_client_id_invalid");
  return uniqueValidIds([normalized, ...existing]);
}

function uniqueValidIds(values: readonly string[]): string[] {
  const unique: string[] = [];
  for (const value of values) {
    const normalized = normalizeClientId(value);
    if (normalized && !unique.includes(normalized)) unique.push(normalized);
    if (unique.length === MAX_SAVED_CLIENT_IDS) break;
  }
  return unique;
}

function normalizeClientId(value: string): string | null {
  const normalized = value.trim().toLowerCase();
  return UUID_PATTERN.test(normalized) ? normalized : null;
}
