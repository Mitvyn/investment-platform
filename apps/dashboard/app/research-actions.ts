"use server";

import { redirect } from "next/navigation";

import {
  buildResearchRunRequestFromFormFields,
  enqueueResearchRunCommand,
} from "../lib/research-run-launcher";
import { createClient } from "../lib/supabase/server";

export async function launchResearchRun(formData: FormData) {
  const supabase = await createClient();
  const { data: authData, error: authError } = await supabase.auth.getClaims();
  const claims = authData?.claims;
  const operatorId = claims?.sub;
  if (authError || !claims || typeof operatorId !== "string") {
    redirect("/login");
  }

  const securityId = String(formData.get("securityId") ?? "").trim();
  const cutoffInput = String(formData.get("asOfCutoff") ?? "").trim();
  const operatorFocus = String(formData.get("operatorFocus") ?? "");
  let commandId: string;
  try {
    const receipt = await enqueueResearchRunCommand(
      supabase,
      claims,
      buildResearchRunRequestFromFormFields({
        securityId,
        asOfCutoff: cutoffInput,
        operatorFocus,
      }),
      new Date(),
    );
    commandId = receipt.command_id;
  } catch (error) {
    const errorCode =
      error instanceof TypeError ||
      (error instanceof Error &&
        /invalid|unsupported|future|cannot alter|exceeds/.test(error.message))
        ? "invalid_request"
        : "enqueue_failed";
    redirect(
      `/?security=${encodeURIComponent(securityId)}&research_error=${errorCode}`,
    );
  }

  redirect(
    `/?security=${encodeURIComponent(securityId)}&research_command=${commandId}`,
  );
}
