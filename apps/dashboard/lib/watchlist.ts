import type { WatchlistItem } from "@iros/types";

import { createClient } from "./supabase/server";
import {
  resolveWatchlistRows,
  type WatchlistRow,
  type WatchlistSecurityRow,
} from "./watchlist-identity";

export async function loadWatchlist(): Promise<WatchlistItem[]> {
  const supabase = await createClient();
  const [{ data: securityData, error: securityError }, watchlistResult] =
    await Promise.all([
      supabase.from("iros_securities").select("id,symbol,issuer_name"),
      supabase
        .from("iros_watchlist_items")
        .select("security_id,ticker,company_name,disposition,added_at,updated_at")
        .order("updated_at", { ascending: false }),
    ]);

  if (securityError) {
    throw new Error(`Watchlist security API failed: ${securityError.message}`);
  }

  let { data, error } = watchlistResult;

  if (error) {
    const legacy = await supabase
      .from("iros_watchlist_items")
      .select("ticker,company_name,disposition,added_at,updated_at")
      .order("updated_at", { ascending: false });
    data = legacy.data?.map((row) => ({ ...row, security_id: null })) ?? null;
    error = legacy.error;
  }
  if (error) {
    throw new Error(`Watchlist API failed: ${error.message}`);
  }

  return resolveWatchlistRows(
    (data ?? []) as WatchlistRow[],
    (securityData ?? []) as WatchlistSecurityRow[],
  );
}
