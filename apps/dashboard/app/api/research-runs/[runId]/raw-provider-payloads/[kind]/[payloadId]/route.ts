import { NextResponse } from "next/server";

import {
  readRawProviderPayload,
  type RawProviderPayloadKind,
} from "@/lib/raw-provider-audit";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const noStoreHeaders = { "Cache-Control": "private, no-store" };

export async function GET(
  _request: Request,
  context: {
    params: Promise<{ runId: string; kind: string; payloadId: string }>;
  },
) {
  const { runId, kind, payloadId } = await context.params;
  if (kind !== "grader" && kind !== "synthesis") {
    return NextResponse.json(
      { error: "Raw provider payload not found." },
      { status: 404, headers: noStoreHeaders },
    );
  }

  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  if (error || data?.claims === undefined) {
    return NextResponse.json(
      { error: "Authentication required." },
      { status: 401, headers: noStoreHeaders },
    );
  }

  try {
    const payload = await readRawProviderPayload(
      supabase,
      data.claims,
      {
        researchRunId: runId,
        payloadKind: kind as RawProviderPayloadKind,
        payloadId,
      },
    );
    return NextResponse.json(payload, { headers: noStoreHeaders });
  } catch (auditError) {
    const message =
      auditError instanceof Error ? auditError.message : "audit access failed";
    const status = message.includes("permission required") ? 403 : 404;
    return NextResponse.json(
      { error: status === 403 ? "Permission required." : "Payload not found." },
      { status, headers: noStoreHeaders },
    );
  }
}
