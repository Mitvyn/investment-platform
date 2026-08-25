"use server";

import { redirect } from "next/navigation";
import { cookies } from "next/headers";

import {
  beginMoomooDesktopConnection,
  composeMoomooDesktopSnapshots,
  disconnectMoomooDesktop,
  disconnectMoomooAll,
  disconnectMoomooMcp,
  beginMoomooMcpAuthorization,
  MoomooMcpCommandError,
  discoverMoomooMcpTools,
  fetchMoomooMarketHistoryEvidence,
  fetchMoomooMarketQuoteEvidence,
  refreshMoomooDesktopHoldings,
  refreshMoomooMcpHoldings,
  replaceMoomooDesktopQuoteSubscriptions,
  resumeMoomooDesktopConnection,
  resumeMoomooMcpConnection,
} from "@/lib/moomoo-desktop";
import { persistMoomooPortfolioMirror } from "@/lib/portfolio-persistence";
import {
  addMoomooClientId,
  isMoomooMcpAutoResumeEnabled,
  MOOMOO_AUTO_RESUME_COOKIE,
  MOOMOO_CLIENT_IDS_COOKIE,
  MOOMOO_MCP_AUTO_RESUME_COOKIE,
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

export async function refreshMoomooMcpPortfolio(formData: FormData) {
  const { operatorId, suffix } = await authenticatedOperator(formData);
  try {
    await refreshMoomooMcpHoldings({ operatorId });
  } catch {
    redirect(`/?moomoo_error=mcp_portfolio_refresh_failed${suffix}`);
  }
  redirect(`/?moomoo=mcp_portfolio_refreshed${suffix}`);
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

export async function discoverMoomooMcp(formData: FormData) {
  const { operatorId, suffix } = await authenticatedOperator(formData);
  try {
    await discoverMoomooMcpTools({ operatorId });
  } catch {
    redirect(`/?mcp_error=discovery_failed${suffix}`);
  }
  redirect(`/?mcp=discovered${suffix}`);
}

export async function authorizeMoomooMcp(formData: FormData) {
  const { operatorId, suffix } = await authenticatedOperator(formData);
  try {
    await beginMoomooMcpAuthorization({ operatorId });
    const cookieStore = await cookies();
    cookieStore.set(MOOMOO_MCP_AUTO_RESUME_COOKIE, "enabled", {
      httpOnly: true,
      maxAge: 60 * 60 * 24 * 365,
      path: "/",
      sameSite: "strict",
    });
  } catch (error) {
    const errorCode =
      error instanceof MoomooMcpCommandError
        ? error.code
        : "authorization_failed";
    redirect(`/?mcp_error=${encodeURIComponent(errorCode)}${suffix}`);
  }
  redirect(`/?mcp=authorizing${suffix}`);
}

/**
 * Silent, one-shot startup resume for the core Moomoo (MCP) connection.
 *
 * Independent of the optional OpenAPI `resumeMoomooSilently` above: it never
 * reads or writes the OpenAPI client-ID cookie, and its outcome (including
 * failure) never affects the OpenAPI connection. Called client-side once per
 * page load by `MoomooMcpAutoReconnect`; requires no browser redirect and no
 * manual discovery button on success.
 */
export async function resumeMoomooMcpSilently(): Promise<boolean> {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  const operatorId = data?.claims?.sub;
  if (error || typeof operatorId !== "string") return false;
  const cookieStore = await cookies();
  if (
    !isMoomooMcpAutoResumeEnabled(
      cookieStore.get(MOOMOO_MCP_AUTO_RESUME_COOKIE)?.value,
    )
  ) {
    return false;
  }
  try {
    const status = await resumeMoomooMcpConnection({ operatorId });
    return status.state === "ready";
  } catch {
    return false;
  }
}

export async function disconnectMoomooMcpAction(formData: FormData) {
  const { operatorId, suffix } = await authenticatedOperator(formData);
  try {
    await disconnectMoomooMcp({ operatorId });
    const cookieStore = await cookies();
    cookieStore.set(MOOMOO_MCP_AUTO_RESUME_COOKIE, "disabled", {
      httpOnly: true,
      maxAge: 60 * 60 * 24 * 365,
      path: "/",
      sameSite: "strict",
    });
  } catch {
    redirect(`/?mcp_error=disconnect_failed${suffix}`);
  }
  redirect(`/?mcp=disconnected${suffix}`);
}

export async function disconnectMoomooAllAction(formData: FormData) {
  const { operatorId, suffix } = await authenticatedOperator(formData);
  try {
    await disconnectMoomooAll({ operatorId });
    const cookieStore = await cookies();
    cookieStore.delete(MOOMOO_AUTO_RESUME_COOKIE);
    cookieStore.delete(MOOMOO_MCP_AUTO_RESUME_COOKIE);
    cookieStore.delete(MOOMOO_CLIENT_IDS_COOKIE);
  } catch {
    redirect(`/?moomoo_error=clear_all_failed${suffix}`);
  }
  redirect(`/?moomoo=disconnected&mcp=disconnected${suffix}`);
}

export async function refreshMarketEvidence(formData: FormData) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  const operatorId = data?.claims?.sub;
  if (error || typeof operatorId !== "string") redirect("/login");

  const securityId = String(formData.get("securityId") ?? "").trim();
  const suffix = dashboardSuffix(formData);
  let failureReason: string | null = null;
  let resultState: "ready" | "stale" | null = null;
  try {
    const { data: security, error: securityError } = await supabase
      .from("iros_securities")
      .select("id,symbol")
      .eq("id", securityId)
      .maybeSingle();
    if (
      securityError ||
      !security ||
      !/^[A-Z][A-Z0-9.\-]{0,15}$/.test(security.symbol)
    ) {
      throw new Error("security_unauthorized");
    }
    const status = await fetchMoomooMarketQuoteEvidence({
      operatorId,
      securityId: String(security.id),
      ticker: `US.${security.symbol}`,
    });
    if (status.state === "ready" || status.state === "stale") {
      resultState = status.state;
    } else {
      failureReason = status.errorCode ?? status.state;
    }
  } catch (thrown) {
    failureReason =
      thrown instanceof Error && thrown.message === "security_unauthorized"
        ? "security_unauthorized"
        : "request_failed";
  }
  if (failureReason) {
    redirect(`/?market_evidence_error=${failureReason}${suffix}`);
  }
  redirect(`/?market_evidence=${resultState}${suffix}`);
}

export async function refreshMarketHistory(formData: FormData) {
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
    if (
      securityError ||
      !security ||
      !/^[A-Z][A-Z0-9.\-]{0,15}$/.test(security.symbol)
    ) throw new Error("security_unauthorized");
    const end = new Date();
    const start = new Date(end);
    start.setUTCDate(start.getUTCDate() - 120);
    const status = await fetchMoomooMarketHistoryEvidence({
      end: end.toISOString().slice(0, 10),
      maxBars: 100,
      operatorId,
      securityId: String(security.id),
      start: start.toISOString().slice(0, 10),
      ticker: `US.${security.symbol}`,
    });
    if (status.state !== "ready") {
      redirect(`/?market_history_error=${status.errorCode ?? status.state}${suffix}`);
    }
  } catch (thrown) {
    if (thrown instanceof Error && thrown.message === "security_unauthorized") {
      redirect(`/?market_history_error=security_unauthorized${suffix}`);
    }
    throw thrown;
  }
  redirect(`/?market_history=ready${suffix}`);
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
