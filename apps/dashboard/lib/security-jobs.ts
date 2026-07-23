import { createSecurityJobLoader, type SecurityJobRow } from "./security-job-loader";
import { createClient } from "./supabase/server";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const loadFromRows = createSecurityJobLoader(async (operatorId, jobId) => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_jobs")
    .select(
      "id,operator_id,job_type,job_state,idempotency_key,ticker,security_id,error_code,created_at,updated_at",
    )
    .eq("operator_id", operatorId)
    .eq("id", jobId)
    .limit(2);
  if (error) {
    throw new Error(`Security onboarding status failed: ${error.message}`);
  }
  return (data ?? []) as SecurityJobRow[];
});

export async function loadSecurityJob(operatorId: string, jobId: string) {
  if (!UUID_PATTERN.test(operatorId) || !UUID_PATTERN.test(jobId)) return null;
  return loadFromRows(operatorId, jobId);
}
