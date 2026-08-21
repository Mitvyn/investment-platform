type DesktopEnvironment = Record<string, string | undefined>;
type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export type ImportedResearchCapture = {
  acceptedAt: string;
  asOfCutoff: string;
  captureContentHash: string;
  captureId: string;
  captureRevision: number;
  questionType: string;
  questionTypeVersion: string;
  workflowConfigVersion: string;
};

export type ResearchCaptureImportRequest = {
  archivePath: string;
  asOfCutoff: string;
  cik: string;
  issuerName: string;
  operatorId: string;
  primaryListingExchange: string;
  securityId: string;
  trustedIssuerHosts: string[];
};

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CONTROL_ORIGIN_PATTERN = /^http:\/\/127\.0\.0\.1:\d+$/;

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

function isImportReceipt(value: unknown): value is {
  accepted_at: string;
  as_of_cutoff: string;
  capture_content_hash: string;
  capture_id: string;
  capture_revision: number;
  contract_version: "primary_source_capture_import_receipt.v1";
  question_type: string;
  question_type_version: string;
  workflow_config_version: string;
} {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate.contract_version === "primary_source_capture_import_receipt.v1" &&
    typeof candidate.accepted_at === "string" &&
    typeof candidate.as_of_cutoff === "string" &&
    typeof candidate.capture_content_hash === "string" &&
    typeof candidate.capture_id === "string" &&
    Number.isInteger(candidate.capture_revision) &&
    typeof candidate.question_type === "string" &&
    typeof candidate.question_type_version === "string" &&
    typeof candidate.workflow_config_version === "string"
  );
}

export async function importResearchCapture(
  request: ResearchCaptureImportRequest,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<ImportedResearchCapture> {
  if (
    !UUID_PATTERN.test(request.operatorId) ||
    !UUID_PATTERN.test(request.securityId)
  ) {
    throw new TypeError("capture import identity is invalid");
  }
  if (!request.archivePath.trim() || !request.archivePath.startsWith("/")) {
    throw new TypeError("capture import archive path is invalid");
  }
  const trustedIssuerHosts = request.trustedIssuerHosts
    .map((host) => host.trim().toLowerCase())
    .filter((host) => host.length > 0);
  if (trustedIssuerHosts.length === 0) {
    throw new TypeError("capture import trusted issuer hosts are required");
  }
  const contract = controlContract(environment);
  if (!contract) {
    throw new Error("Desktop capture import service is unavailable");
  }
  const response = await fetcher(`${contract.origin}/v1/research/captures/import`, {
    body: JSON.stringify({
      archive_path: request.archivePath.trim(),
      as_of_cutoff: request.asOfCutoff,
      cik: request.cik,
      issuer_name: request.issuerName,
      operator_id: request.operatorId,
      primary_listing_exchange: request.primaryListingExchange,
      security_id: request.securityId,
      trusted_issuer_hosts: trustedIssuerHosts,
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
  if (!response.ok || !isImportReceipt(payload)) {
    throw new Error("capture import request failed");
  }
  return {
    acceptedAt: payload.accepted_at,
    asOfCutoff: payload.as_of_cutoff,
    captureContentHash: payload.capture_content_hash,
    captureId: payload.capture_id,
    captureRevision: payload.capture_revision,
    questionType: payload.question_type,
    questionTypeVersion: payload.question_type_version,
    workflowConfigVersion: payload.workflow_config_version,
  };
}
