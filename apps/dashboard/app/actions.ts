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

export async function toggleRxrxWatchlist() {
  const supabase = await createClient();
  const { data: authData, error: authError } = await supabase.auth.getClaims();
  const operatorId = authData?.claims?.sub;
  if (authError || typeof operatorId !== "string") {
    redirect("/login");
  }

  const { data: existing, error: readError } = await supabase
    .from("iros_watchlist_items")
    .select("id")
    .eq("operator_id", operatorId)
    .eq("ticker", "RXRX")
    .maybeSingle();
  if (readError) throw new Error(`Watchlist read failed: ${readError.message}`);

  if (existing) {
    const { error } = await supabase
      .from("iros_watchlist_items")
      .delete()
      .eq("id", existing.id)
      .eq("operator_id", operatorId);
    if (error) throw new Error(`Watchlist delete failed: ${error.message}`);
  } else {
    const { error } = await supabase.from("iros_watchlist_items").insert({
      id: randomUUID(),
      operator_id: operatorId,
      ticker: "RXRX",
      company_name: "Recursion Pharmaceuticals, Inc.",
      disposition: "monitor",
    });
    if (error) throw new Error(`Watchlist insert failed: ${error.message}`);
  }
  revalidatePath("/");
}
