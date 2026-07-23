import type { ResearchRun } from "@iros/types";

type LoadResearchRun = (
  operatorId: string,
  runId: string,
) => Promise<ResearchRun | null>;

type WorkspaceResolution =
  | { kind: "redirect"; location: "/login" }
  | { kind: "not_found" }
  | { kind: "ready"; run: ResearchRun };

export type ResearchRunWorkspaceField = {
  label: string;
  value: string;
};

export function presentResearchRunState(
  passed: boolean,
  kind: "eligibility" | "check",
): {
  label: "Eligible" | "Not eligible" | "Pass" | "Fail";
  variant: "verified" | "destructive";
} {
  if (passed) {
    return {
      label: kind === "eligibility" ? "Eligible" : "Pass",
      variant: "verified",
    };
  }
  return {
    label: kind === "eligibility" ? "Not eligible" : "Fail",
    variant: "destructive",
  };
}

export function researchRunWorkspaceFields(run: ResearchRun): {
  identity: ResearchRunWorkspaceField[];
  contract: ResearchRunWorkspaceField[];
  audit: ResearchRunWorkspaceField[];
} {
  return {
    identity: [
      { label: "Security ID", value: run.security_id },
      { label: "CIK", value: run.security_identity.cik },
      {
        label: "Primary listing",
        value: run.security_identity.primary_listing_exchange,
      },
      { label: "Run ID", value: run.id },
    ],
    contract: [
      { label: "Contract version", value: run.contract_version },
      { label: "Question type", value: run.question_type },
      { label: "Question version", value: run.question_type_version },
      { label: "Workflow", value: run.workflow_config_version },
      { label: "Thesis contract", value: run.thesis_contract_id },
      { label: "Cutoff", value: run.as_of_cutoff },
    ],
    audit: [
      { label: "Idempotency key", value: run.idempotency_key },
      { label: "Created", value: run.created_at },
      { label: "Run status", value: run.status },
      { label: "Eligibility policy", value: run.eligibility.policy_version },
    ],
  };
}

export async function resolveResearchRunWorkspace({
  operatorId,
  runId,
  loadRun,
}: {
  operatorId: string | null;
  runId: string;
  loadRun: LoadResearchRun;
}): Promise<WorkspaceResolution> {
  if (operatorId === null) {
    return { kind: "redirect", location: "/login" };
  }

  const run = await loadRun(operatorId, runId);
  if (run === null || run.operator_id !== operatorId) {
    return { kind: "not_found" };
  }
  return { kind: "ready", run };
}
