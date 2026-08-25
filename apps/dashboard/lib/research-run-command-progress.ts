import {
  createResearchRunCommandProgressLoader,
  type ResearchRunCommandProgressViewRow,
} from "./research-run-command-progress-loader.ts";
import {
  isLocalResearchRuntimeReady,
  loadLocalResearchRunCommandProgress,
} from "./research-run-local.ts";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

async function fetchResearchRunCommandProgressRows(
  operatorId: string,
  commandId: string,
): Promise<ResearchRunCommandProgressViewRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_research_run_command_progress")
    .select("operator_id,command_id,canonical_progress")
    .eq("operator_id", operatorId)
    .eq("command_id", commandId)
    .limit(2);
  if (error) {
    throw new Error("Research Run command progress unavailable");
  }
  return (data ?? []) as unknown as ResearchRunCommandProgressViewRow[];
}

const loadFromCanonicalView = createResearchRunCommandProgressLoader(
  fetchResearchRunCommandProgressRows,
);

export async function loadResearchRunCommandProgress(
  operatorId: string,
  commandId: string,
) {
  if (!UUID_PATTERN.test(operatorId) || !UUID_PATTERN.test(commandId)) {
    return null;
  }
  if (isLocalResearchRuntimeReady()) {
    return loadLocalResearchRunCommandProgress(operatorId, commandId);
  }
  return loadFromCanonicalView(operatorId, commandId);
}
