import {
  parsePreparedResearchCaptureIdentity,
  type PreparedResearchCaptureIdentity,
} from "../../../packages/types/research-run-command.ts";
import type {
  ResearchQuestionType,
  ResearchQuestionTypeVersion,
  ResearchQuestionRequest,
  ResearchWorkflowConfigVersion,
} from "../../../packages/types/research-run.ts";
import {
  normalizeResearchQuestionRequest,
  parseResearchQuestionRequest,
} from "../../../packages/types/research-run.ts";

type DesktopEnvironment = Record<string, string | undefined>;
type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export type AcceptedResearchCapture = PreparedResearchCaptureIdentity & {
  accepted_at: string;
  as_of_cutoff: string;
  question_type: ResearchQuestionType;
  question_type_version: ResearchQuestionTypeVersion;
  workflow_config_version: ResearchWorkflowConfigVersion;
};

export type AcceptedResearchCaptureRequest = {
  operatorId: string;
  securityId: string;
};

export type AcceptedResearchCaptureList = {
  captures: AcceptedResearchCapture[];
  detail: string;
  state: "failed" | "ready" | "unavailable";
};

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CONTROL_ORIGIN_PATTERN = /^http:\/\/127\.0\.0\.1:\d+$/;
const MAX_CAPTURE_OPTIONS = 50;
const CAPTURE_KEYS = [
  "accepted_at",
  "as_of_cutoff",
  "capture_content_hash",
  "capture_id",
  "capture_revision",
  "question_type",
  "question_type_version",
  "workflow_config_version",
] as const;

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

function isTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /(?:z|[+-]\d{2}:\d{2})$/i.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}

function validateRequest(request: AcceptedResearchCaptureRequest) {
  if (
    !UUID_PATTERN.test(request.operatorId) ||
    !UUID_PATTERN.test(request.securityId)
  ) {
    throw new TypeError("invalid accepted capture request");
  }
}

function parseCapture(
  value: unknown,
  request: AcceptedResearchCaptureRequest,
): AcceptedResearchCapture {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("invalid accepted capture");
  }
  const candidate = value as Record<string, unknown>;
  const actualKeys = Object.keys(candidate).sort();
  const expectedKeys = [...CAPTURE_KEYS].sort();
  const identity = parsePreparedResearchCaptureIdentity({
    capture_id: candidate.capture_id,
    capture_revision: candidate.capture_revision,
    capture_content_hash: candidate.capture_content_hash,
  });
  const normalized = normalizeResearchQuestionRequest(
    parseResearchQuestionRequest({
      question_type: candidate.question_type,
      security_id: request.securityId,
      as_of_cutoff: candidate.as_of_cutoff,
      workflow_config_version: candidate.workflow_config_version,
      operator_focus: null,
    }),
  );
  if (
    actualKeys.length !== expectedKeys.length ||
    actualKeys.some((key, index) => key !== expectedKeys[index]) ||
    !isTimestamp(candidate.accepted_at) ||
    candidate.as_of_cutoff !== normalized.as_of_cutoff ||
    candidate.question_type !== normalized.question_type ||
    candidate.question_type_version !== normalized.question_type_version ||
    candidate.workflow_config_version !== normalized.workflow_config_version
  ) {
    throw new TypeError("invalid accepted capture");
  }
  return { ...candidate, ...identity } as AcceptedResearchCapture;
}

function parseList(
  value: unknown,
  request: AcceptedResearchCaptureRequest,
): AcceptedResearchCapture[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("invalid accepted capture list");
  }
  const payload = value as Record<string, unknown>;
  if (
    Object.keys(payload).sort().join(",") !==
      "capture_count,captures,contract_version" ||
    payload.contract_version !== "accepted_research_capture_list.v1" ||
    !Number.isInteger(payload.capture_count) ||
    !Array.isArray(payload.captures) ||
    payload.captures.length > MAX_CAPTURE_OPTIONS ||
    payload.capture_count !== payload.captures.length
  ) {
    throw new TypeError("invalid accepted capture list");
  }
  const captures = payload.captures.map((capture) =>
    parseCapture(capture, request),
  );
  const identities = captures.map(
    (capture) =>
      `${capture.capture_id}:${capture.capture_revision}:${capture.capture_content_hash}`,
  );
  if (new Set(identities).size !== identities.length) {
    throw new TypeError("duplicate accepted capture identity");
  }
  return captures;
}

export function parseAcceptedResearchCaptureSelection(
  value: unknown,
): PreparedResearchCaptureIdentity {
  if (typeof value !== "string") {
    throw new TypeError("invalid accepted capture selection");
  }
  const [captureId, revision, contentHash, extra] = value.split(":");
  if (extra !== undefined || !/^\d+$/.test(revision ?? "")) {
    throw new TypeError("invalid accepted capture selection");
  }
  try {
    return parsePreparedResearchCaptureIdentity({
      capture_id: captureId,
      capture_revision: Number(revision),
      capture_content_hash: contentHash,
    });
  } catch {
    throw new TypeError("invalid accepted capture selection");
  }
}

export function buildResearchRequestFromAcceptedCapture(
  capture: AcceptedResearchCapture,
  securityId: string,
  operatorFocus: string,
): ResearchQuestionRequest {
  return parseResearchQuestionRequest({
    question_type: capture.question_type,
    security_id: securityId,
    as_of_cutoff: capture.as_of_cutoff,
    workflow_config_version: capture.workflow_config_version,
    operator_focus: operatorFocus,
  });
}

export async function loadAcceptedResearchCaptures(
  request: AcceptedResearchCaptureRequest,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<AcceptedResearchCaptureList> {
  validateRequest(request);
  const contract = controlContract(environment);
  if (!contract) {
    return {
      captures: [],
      detail: "Open desktop app to prepare and select accepted evidence",
      state: "unavailable",
    };
  }
  const url = new URL("/v1/research/captures", contract.origin);
  url.searchParams.set("operator_id", request.operatorId);
  url.searchParams.set("security_id", request.securityId);
  try {
    const response = await fetcher(url, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${contract.token}` },
      signal: AbortSignal.timeout(3_000),
    });
    if (!response.ok) throw new Error("capture list request failed");
    const captures = parseList(await response.json(), request);
    return {
      captures,
      detail:
        captures.length === 0
          ? "No accepted capture matches this exact research request"
          : `${captures.length} accepted capture${captures.length === 1 ? "" : "s"} available`,
      state: "ready",
    };
  } catch {
    return {
      captures: [],
      detail: "Accepted capture list unavailable",
      state: "failed",
    };
  }
}

export async function resolveAcceptedResearchCapture(
  request: AcceptedResearchCaptureRequest & {
    selectedCapture: PreparedResearchCaptureIdentity;
  },
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<AcceptedResearchCapture> {
  const selected = parsePreparedResearchCaptureIdentity({
    capture_id: request.selectedCapture.capture_id,
    capture_revision: request.selectedCapture.capture_revision,
    capture_content_hash: request.selectedCapture.capture_content_hash,
  });
  const result = await loadAcceptedResearchCaptures(request, environment, fetcher);
  const exact = result.captures.find(
    (capture) =>
      capture.capture_id === selected.capture_id &&
      capture.capture_revision === selected.capture_revision &&
      capture.capture_content_hash === selected.capture_content_hash,
  );
  if (!exact) throw new Error("selected accepted capture is unavailable");
  return exact;
}
