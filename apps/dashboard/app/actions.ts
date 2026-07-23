"use server";

import { randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { createClient } from "../lib/supabase/server";

export async function signOut() {
  const supabase = await createClient();
  await supabase.auth.signOut();
  redirect("/login");
}

const SECURITY_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function toggleWatchlist(formData: FormData) {
  const supabase = await createClient();
  const { data: authData, error: authError } = await supabase.auth.getClaims();
  const operatorId = authData?.claims?.sub;
  if (authError || typeof operatorId !== "string") {
    redirect("/login");
  }
  const securityId = String(formData.get("securityId") ?? "").trim();
  if (!SECURITY_ID_PATTERN.test(securityId)) {
    throw new Error("Watchlist security identity is invalid");
  }

  const { data: security, error: securityError } = await supabase
    .from("iros_securities")
    .select("id,symbol,issuer_name")
    .eq("operator_id", operatorId)
    .eq("id", securityId)
    .maybeSingle();
  if (securityError) {
    throw new Error(`Security lookup failed: ${securityError.message}`);
  }
  if (!security) throw new Error("Watchlist security does not exist");

  const [stableResult, legacyResult] = await Promise.all([
    supabase
      .from("iros_watchlist_items")
      .select("id")
      .eq("operator_id", operatorId)
      .eq("security_id", securityId),
    supabase
      .from("iros_watchlist_items")
      .select("id")
      .eq("operator_id", operatorId)
      .is("security_id", null)
      .eq("ticker", security.symbol),
  ]);
  const readError = stableResult.error ?? legacyResult.error;
  if (readError) {
    throw new Error(`Watchlist read failed: ${readError.message}`);
  }
  const watchlistIds = [
    ...(stableResult.data ?? []),
    ...(legacyResult.data ?? []),
  ].map((row) => row.id);

  if (watchlistIds.length) {
    const { error } = await supabase
      .from("iros_watchlist_items")
      .delete()
      .eq("operator_id", operatorId)
      .in("id", watchlistIds);
    if (error) throw new Error(`Watchlist delete failed: ${error.message}`);
  } else {
    const { error } = await supabase.from("iros_watchlist_items").insert({
      id: randomUUID(),
      operator_id: operatorId,
      security_id: securityId,
      ticker: security.symbol,
      company_name: security.issuer_name,
      disposition: "monitor",
    });
    if (error) throw new Error(`Watchlist insert failed: ${error.message}`);
  }
  revalidatePath("/");
}
