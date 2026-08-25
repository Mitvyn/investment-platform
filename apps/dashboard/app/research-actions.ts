"use server";

import { redirect } from "next/navigation";

import { enqueueResearchRunCommand } from "../lib/research-run-launcher";
import {
  enqueueLocalResearchRunCommand,
  isLocalResearchRuntimeReady,
} from "../lib/research-run-local";
import {
  buildResearchRequestFromAcceptedCapture,
  parseAcceptedResearchCaptureSelection,
  resolveAcceptedResearchCapture,
} from "../lib/research-desktop";
import { createClient } from "../lib/supabase/server";
import { loadSecurityDirectory } from "../lib/securities";

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
    if (isLocalResearchRuntimeReady()) {
      const security = (await loadSecurityDirectory()).find(
        (entry) => entry.securityId === securityId,
      );
      if (!security) throw new Error("Research Run security is unavailable");
      const local = await enqueueLocalResearchRunCommand({
        operatorId,
        securityId,
        ticker: security.ticker,
        request,
        preparedCapture,
        now: new Date(),
      });
      commandId = local.receipt.command_id;
    } else {
      const receipt = await enqueueResearchRunCommand(
        supabase,
        claims,
        request,
        preparedCapture,
        new Date(),
      );
      commandId = receipt.command_id;
    }
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
