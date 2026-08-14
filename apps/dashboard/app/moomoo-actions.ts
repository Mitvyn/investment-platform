"use server";

import { redirect } from "next/navigation";
import { cookies } from "next/headers";

import {
  beginMoomooDesktopConnection,
  composeMoomooDesktopSnapshots,
  disconnectMoomooDesktop,
  refreshMoomooDesktopHoldings,
  replaceMoomooDesktopQuoteSubscriptions,
  resumeMoomooDesktopConnection,
} from "@/lib/moomoo-desktop";
import { persistMoomooPortfolioMirror } from "@/lib/portfolio-persistence";
import {
  addMoomooClientId,
  MOOMOO_AUTO_RESUME_COOKIE,
  MOOMOO_CLIENT_IDS_COOKIE,
  parseMoomooClientIds,
  serializeMoomooClientIds,
} from "@/lib/moomoo-client-preferences";
import { createClient } from "@/lib/supabase/server";

export async function connectMoomoo(formData: FormData) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  const operatorId = data?.claims?.sub;
  if (error || typeof operatorId !== "string") redirect("/login");

  const clientId = String(formData.get("clientId") ?? "").trim();
  const suffix = dashboardSuffix(formData);
  try {
    await beginMoomooDesktopConnection({ clientId, operatorId });
    const cookieStore = await cookies();
    const savedClientIds = addMoomooClientId(
      parseMoomooClientIds(cookieStore.get(MOOMOO_CLIENT_IDS_COOKIE)?.value),
      clientId,
    );
    cookieStore.set(
      MOOMOO_CLIENT_IDS_COOKIE,
      serializeMoomooClientIds(savedClientIds),
      {
        httpOnly: true,
        maxAge: 60 * 60 * 24 * 365,
        path: "/",
        sameSite: "strict",
      },
    );
    cookieStore.set(MOOMOO_AUTO_RESUME_COOKIE, clientId.toLowerCase(), {
      httpOnly: true,
      maxAge: 60 * 60 * 24 * 365,
      path: "/",
      sameSite: "strict",
    });
  } catch {
    redirect(`/?moomoo_error=connection_failed${suffix}`);
  }
  redirect(`/?moomoo=connecting${suffix}`);
}

export async function refreshMoomoo(formData: FormData) {
  const { operatorId, suffix } = await authenticatedOperator(formData);
  try {
    await refreshMoomooDesktopHoldings({ operatorId });
  } catch {
    redirect(`/?moomoo_error=refresh_failed${suffix}`);
  }
  redirect(`/?moomoo=refreshed${suffix}`);
}

export async function disconnectMoomoo(formData: FormData) {
  const { operatorId, suffix } = await authenticatedOperator(formData);
  try {
    await disconnectMoomooDesktop({ operatorId });
    const cookieStore = await cookies();
    cookieStore.set(MOOMOO_AUTO_RESUME_COOKIE, "disabled", {
      httpOnly: true,
      maxAge: 60 * 60 * 24 * 365,
      path: "/",
      sameSite: "strict",
    });
  } catch {
    redirect(`/?moomoo_error=disconnect_failed${suffix}`);
  }
  redirect(`/?moomoo=disconnected${suffix}`);
}

export async function resumeMoomooSilently(clientId: string): Promise<boolean> {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  const operatorId = data?.claims?.sub;
  if (error || typeof operatorId !== "string") return false;
  try {
    await resumeMoomooDesktopConnection({ clientId, operatorId });
    const cookieStore = await cookies();
    cookieStore.set(MOOMOO_AUTO_RESUME_COOKIE, clientId.toLowerCase(), {
      httpOnly: true,
      maxAge: 60 * 60 * 24 * 365,
      path: "/",
      sameSite: "strict",
    });
    return true;
  } catch {
    return false;
  }
}

export async function startMoomooLiveQuote(formData: FormData) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  const operatorId = data?.claims?.sub;
  if (error || typeof operatorId !== "string") redirect("/login");
  const securityId = String(formData.get("securityId") ?? "").trim();
  const suffix = dashboardSuffix(formData);
  try {
    const { data: security, error: securityError } = await supabase
      .from("iros_securities")
      .select("id,symbol")
      .eq("id", securityId)
      .maybeSingle();
    if (securityError || !security || !/^[A-Z][A-Z0-9.\-]{0,15}$/.test(security.symbol)) {
      throw new Error("security_unavailable");
    }
    await replaceMoomooDesktopQuoteSubscriptions({
      operatorId,
      symbols: [`US.${security.symbol}`],
    });
  } catch {
    redirect(`/?moomoo_error=quote_failed${suffix}`);
  }
  redirect(`/?moomoo=quote_started${suffix}`);
}

export async function stopMoomooLiveQuote(formData: FormData) {
  const { operatorId, suffix } = await authenticatedOperator(formData);
  try {
    await replaceMoomooDesktopQuoteSubscriptions({ operatorId, symbols: [] });
  } catch {
    redirect(`/?moomoo_error=quote_failed${suffix}`);
  }
  redirect(`/?moomoo=quote_stopped${suffix}`);
}

export async function saveMoomooMirror(formData: FormData) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  const operatorId = data?.claims?.sub;
  if (error || typeof operatorId !== "string") redirect("/login");
  const securityId = String(formData.get("securityId") ?? "").trim();
  const suffix = dashboardSuffix(formData);
  try {
    const { data: securityRows, error: securityError } = await supabase
      .from("iros_securities")
      .select("id,symbol,primary_listing_exchange")
      .order("symbol", { ascending: true });
    if (securityError) throw new Error("security_directory_unavailable");
    const checkedAt = new Date();
    const composition = await composeMoomooDesktopSnapshots({
      candidates: (securityRows ?? []).map((row) => ({
        primaryListingExchange: String(row.primary_listing_exchange),
        securityId: String(row.id),
        ticker: String(row.symbol),
      })),
      checkedAt,
      operatorId,
    });
    const receipts = await persistMoomooPortfolioMirror({
      checkedAt,
      composition,
      operatorId,
      rpc: async (name, parameters) => supabase.rpc(name, parameters),
    });
    if (receipts.length === 0) throw new Error("portfolio_snapshot_empty");
  } catch {
    redirect(`/?moomoo_error=persist_failed${suffix}`);
  }
  redirect(`/?moomoo=saved${suffix}`);
}

async function authenticatedOperator(formData: FormData) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  const operatorId = data?.claims?.sub;
  if (error || typeof operatorId !== "string") redirect("/login");
  const securityId = String(formData.get("securityId") ?? "").trim();
  const suffix = dashboardSuffix(formData);
  return { operatorId, suffix };
}

function dashboardSuffix(formData: FormData) {
  const params = new URLSearchParams();
  for (const key of ["security", "view", "stage"] as const) {
    const field = key === "security" ? "securityId" : key;
    const value = String(formData.get(field) ?? "").trim();
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return query ? `&${query}` : "";
}
