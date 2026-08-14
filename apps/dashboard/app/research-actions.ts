"use server";

import { redirect } from "next/navigation";

import { enqueueResearchRunCommand } from "../lib/research-run-launcher";
import {
  buildResearchRequestFromAcceptedCapture,
  parseAcceptedResearchCaptureSelection,
  resolveAcceptedResearchCapture,
} from "../lib/research-desktop";
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
  const operatorFocus = String(formData.get("operatorFocus") ?? "");
  const view = String(formData.get("view") ?? "overview").trim() || "overview";
  const suffix = `&view=${encodeURIComponent(view)}`;
  let commandId: string;
  try {
    const selectedCapture = parseAcceptedResearchCaptureSelection(
      formData.get("captureSelection"),
    );
    const preparedCapture = await resolveAcceptedResearchCapture({
      operatorId,
      securityId,
      selectedCapture,
    });
    const request = buildResearchRequestFromAcceptedCapture(
      preparedCapture,
      securityId,
      operatorFocus,
    );
    const receipt = await enqueueResearchRunCommand(
      supabase,
      claims,
      request,
      preparedCapture,
      new Date(),
    );
    commandId = receipt.command_id;
  } catch (error) {
    const errorCode = error instanceof Error &&
      /selected accepted capture is unavailable/.test(error.message)
      ? "capture_unavailable"
      : error instanceof TypeError ||
      (error instanceof Error &&
        /invalid|unsupported|future|cannot alter|exceeds/.test(error.message))
        ? "invalid_request"
        : "enqueue_failed";
    redirect(
      `/?security=${encodeURIComponent(securityId)}${suffix}&research_error=${errorCode}`,
    );
  }

  redirect(
    `/?security=${encodeURIComponent(securityId)}${suffix}&research_command=${commandId}`,
  );
}
