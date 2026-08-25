// Imported by path rather than through the `@iros/types` alias: the parsers
// are runtime values, and a relative path keeps this module directly runnable
// under `node --test`, the same way the contract package tests itself.
import {
  GENERIC_QUANT_ERROR_CODE,
  isQuantErrorCode,
  parseQuantDatasetStatus,
  parseQuantLocalResult,
  type QuantDatasetStatus,
  type QuantLocalResult,
} from "../../../packages/types/quant-workspace.ts";

/**
 * Client for the desktop-local Quant workspace service.
 *
 * The analysis runs in the local worker, never in the browser and never in a
 * hosted service. This module speaks to it over the authenticated loopback
 * control channel, the same one the Research capture import uses, and it
 * refuses to send anything at all unless the desktop worker has declared
 * itself ready on a loopback origin with a real token.
 *
 * Two boundary rules make this module worth having.
 *
 * **Identity is checked before a request, not after.** The operator and the
 * security must be canonical UUID text, and the dataset path must be absolute.
 * A malformed identity never reaches a route that turns it into a directory.
 *
 * **Only reviewed codes travel.** The worker answers failures with a code from
 * a fixed vocabulary. Anything outside that vocabulary is normalised to a
 * generic code here, so an unexpected string from a future worker version can
 * never be rendered into the page.
 */

type DesktopEnvironment = Record<string, string | undefined>;
type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CONTROL_ORIGIN_PATTERN = /^http:\/\/127\.0\.0\.1:\d+$/;
const REQUEST_TIMEOUT_MS = 120_000;

export class QuantDesktopError extends Error {
  readonly code: string;

  constructor(code: string) {
    super("quant workspace request failed");
    // A code outside the reviewed vocabulary is one the dashboard has no
    // wording for, so it is replaced rather than carried any further.
    this.code = isQuantErrorCode(code) ? code : GENERIC_QUANT_ERROR_CODE;
    this.name = "QuantDesktopError";
  }
}

export type QuantDatasetStatusLoad = {
  available: boolean;
  status: QuantDatasetStatus | null;
};

export type QuantImportRequest = {
  datasetPath: string;
  operatorId: string;
  securityId: string;
};

export type QuantRunRequest = {
  assumptions: Record<string, string | number>;
  operatorId: string;
  securityId: string;
};

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

function requireIdentity(...values: string[]): void {
  for (const value of values) {
    if (!UUID_PATTERN.test(value)) {
      throw new QuantDesktopError("workspace_identity_invalid");
    }
  }
}

async function readReason(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (payload && typeof payload === "object" && !Array.isArray(payload)) {
      const reason = (payload as Record<string, unknown>).reason;
      if (typeof reason === "string") return reason;
      const error = (payload as Record<string, unknown>).error;
      if (typeof error === "string") return error;
    }
  } catch {
    // A body that is not JSON tells us nothing beyond the failure itself.
  }
  return "quant_request_invalid";
}

async function post(
  path: string,
  body: Record<string, unknown>,
  environment: DesktopEnvironment,
  fetcher: FetchLike,
): Promise<unknown> {
  const contract = controlContract(environment);
  if (contract === null) {
    throw new QuantDesktopError("quant_workspace_unavailable");
  }
  let response: Response;
  try {
    response = await fetcher(`${contract.origin}${path}`, {
      body: JSON.stringify(body),
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${contract.token}`,
        "Content-Type": "application/json",
      },
      method: "POST",
      // An analysis is CPU work over a local dataset, so this is generous
      // compared with the read timeouts elsewhere while still bounded.
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch {
    throw new QuantDesktopError("quant_workspace_unavailable");
  }
  if (!response.ok) {
    throw new QuantDesktopError(await readReason(response));
  }
  try {
    return await response.json();
  } catch {
    throw new QuantDesktopError("quant_response_invalid");
  }
}

/**
 * The active dataset for one security, if the desktop workspace is running.
 *
 * Never throws for an absent worker: a dashboard rendering a page has nothing
 * useful to do with an exception there, and `available: false` is the state
 * the page needs to show anyway.
 */
export async function loadQuantDatasetStatus(
  request: { operatorId: string; securityId: string },
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<QuantDatasetStatusLoad> {
  const contract = controlContract(environment);
  if (
    contract === null ||
    !UUID_PATTERN.test(request.operatorId) ||
    !UUID_PATTERN.test(request.securityId)
  ) {
    return { available: false, status: null };
  }
  const query = new URLSearchParams({
    operator_id: request.operatorId,
    security_id: request.securityId,
  });
  try {
    const response = await fetcher(
      `${contract.origin}/v1/quant/dataset?${query.toString()}`,
      {
        cache: "no-store",
        headers: { Authorization: `Bearer ${contract.token}` },
        method: "GET",
        signal: AbortSignal.timeout(10_000),
      },
    );
    if (!response.ok) return { available: true, status: null };
    return { available: true, status: parseQuantDatasetStatus(await response.json()) };
  } catch {
    return { available: false, status: null };
  }
}

/**
 * The last completed analysis for the active dataset, if there is one.
 *
 * Like the dataset status, this never throws: a page that cannot reach the
 * worker renders the same way as a page with no run yet.
 */
export async function loadLatestQuantResult(
  request: { operatorId: string; securityId: string },
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<QuantLocalResult | null> {
  const contract = controlContract(environment);
  if (
    contract === null ||
    !UUID_PATTERN.test(request.operatorId) ||
    !UUID_PATTERN.test(request.securityId)
  ) {
    return null;
  }
  const query = new URLSearchParams({
    operator_id: request.operatorId,
    security_id: request.securityId,
  });
  try {
    const response = await fetcher(
      `${contract.origin}/v1/quant/runs/latest?${query.toString()}`,
      {
        cache: "no-store",
        headers: { Authorization: `Bearer ${contract.token}` },
        method: "GET",
        signal: AbortSignal.timeout(10_000),
      },
    );
    if (!response.ok) return null;
    const payload: unknown = await response.json();
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return null;
    }
    const result = parseQuantLocalResult(
      (payload as Record<string, unknown>).result,
    );
    return result !== null && result.security_id === request.securityId
      ? result
      : null;
  } catch {
    return null;
  }
}

/** Import one local dataset file and make it the active dataset. */
export async function importQuantDataset(
  request: QuantImportRequest,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<QuantDatasetStatus> {
  requireIdentity(request.operatorId, request.securityId);
  const datasetPath = request.datasetPath.trim();
  if (!datasetPath.startsWith("/")) {
    throw new QuantDesktopError("dataset_path_invalid");
  }
  const payload = await post(
    "/v1/quant/dataset/import",
    {
      dataset_path: datasetPath,
      operator_id: request.operatorId,
      security_id: request.securityId,
    },
    environment,
    fetcher,
  );
  const status = parseQuantDatasetStatus(payload);
  if (status === null || status.dataset === null) {
    throw new QuantDesktopError("quant_response_invalid");
  }
  return status;
}

/** Run, or reload, one historical analysis for the active dataset. */
export async function runQuantAnalysis(
  request: QuantRunRequest,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<QuantLocalResult> {
  requireIdentity(request.operatorId, request.securityId);
  const payload = await post(
    "/v1/quant/runs",
    {
      assumptions: request.assumptions,
      operator_id: request.operatorId,
      security_id: request.securityId,
    },
    environment,
    fetcher,
  );
  const result = parseQuantLocalResult(payload);
  if (result === null || result.security_id !== request.securityId) {
    throw new QuantDesktopError("quant_response_invalid");
  }
  return result;
}
