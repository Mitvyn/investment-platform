import {
  parseResearchRunCommandReceipt,
  type ResearchRunCommandReceipt,
} from "../../../packages/types/research-run-command.ts";
import {
  normalizeResearchQuestionRequest,
  parseResearchQuestionRequest,
  type ResearchQuestionRequest,
} from "../../../packages/types/research-run.ts";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type Claims = Record<string, unknown>;

type ResearchRunCommandRpcClient = {
  rpc(
    name: string,
    args: Record<string, string | null>,
  ): PromiseLike<{ data: unknown; error: { message: string } | null }>;
};

export function buildResearchRunRequestFromFormFields(fields: {
  securityId: string;
  asOfCutoff: string;
  operatorFocus: string;
}): ResearchQuestionRequest {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(fields.asOfCutoff)) {
    throw new TypeError("invalid UTC cutoff input");
  }
  return {
    question_type: "biotech_moonshot_catalyst_assessment",
    security_id: fields.securityId,
    as_of_cutoff: `${fields.asOfCutoff}:00Z`,
    workflow_config_version: "biotech-moonshot-catalyst-v1",
    operator_focus: fields.operatorFocus,
  };
}

export async function enqueueResearchRunCommand(
  client: ResearchRunCommandRpcClient,
  claims: Claims,
  request: ResearchQuestionRequest,
  now: Date,
): Promise<ResearchRunCommandReceipt> {
  const operatorId = claims.sub;
  if (typeof operatorId !== "string" || !UUID_PATTERN.test(operatorId)) {
    throw new Error("authenticated operator required");
  }
  if (Number.isNaN(now.getTime())) {
    throw new Error("current time is invalid");
  }
  const normalized = normalizeResearchQuestionRequest(
    parseResearchQuestionRequest(request),
  );
  if (Date.parse(normalized.as_of_cutoff) > now.getTime()) {
    throw new Error("research cutoff cannot be in the future");
  }
  const { data, error } = await client.rpc(
    "iros_enqueue_research_run_command",
    {
      p_security_id: normalized.security_id,
      p_as_of_cutoff: normalized.as_of_cutoff,
      p_operator_focus: normalized.operator_focus_normalized,
    },
  );
  if (error) {
    throw new Error("Research Run enqueue failed");
  }
  if (!Array.isArray(data) || data.length !== 1) {
    throw new Error("Research Run enqueue returned invalid receipt count");
  }
  const receipt = parseResearchRunCommandReceipt(data[0]);
  if (
    receipt.operator_id !== operatorId ||
    receipt.security_id !== normalized.security_id ||
    receipt.question_type_version !== normalized.question_type_version ||
    receipt.workflow_config_version !== normalized.workflow_config_version ||
    receipt.as_of_cutoff !== normalized.as_of_cutoff ||
    receipt.operator_focus_normalized !==
      normalized.operator_focus_normalized
  ) {
    throw new Error("Research Run command identity mismatch");
  }
  return receipt;
}
