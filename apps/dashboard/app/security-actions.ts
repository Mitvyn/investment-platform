"use server";

import { redirect } from "next/navigation";

import { enqueueSecurityRegistration } from "../lib/security-registration";
import { createClient } from "../lib/supabase/server";

export async function registerSecurity(formData: FormData) {
  const supabase = await createClient();
  const { data: authData, error: authError } = await supabase.auth.getClaims();
  const claims = authData?.claims;
  const operatorId = claims?.sub;
  if (authError || !claims || typeof operatorId !== "string") {
    redirect("/login");
  }

  let receipt;
  try {
    receipt = await enqueueSecurityRegistration(
      supabase,
      claims,
      {
        contract_version: "security_registration_request.v1",
        ticker: String(formData.get("ticker") ?? ""),
      },
    );
  } catch (error) {
    const errorCode =
      error instanceof Error && error.message === "ticker has invalid format"
        ? "invalid_ticker"
        : "enqueue_failed";
    redirect(`/?registration_error=${errorCode}`);
  }

  redirect(`/?registration=${receipt.job_id}`);
}
