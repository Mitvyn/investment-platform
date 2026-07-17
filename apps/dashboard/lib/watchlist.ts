import type { WatchlistItem } from "@iros/types";

import { createClient } from "./supabase/server";

type WatchlistRow = {
  ticker: string;
  company_name: string;
  disposition: WatchlistItem["disposition"];
  added_at: string;
  updated_at: string;
};

export async function loadWatchlist(): Promise<WatchlistItem[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_watchlist_items")
    .select("ticker,company_name,disposition,added_at,updated_at")
    .order("updated_at", { ascending: false });

  if (error) {
    throw new Error(`Watchlist API failed: ${error.message}`);
  }

  return ((data ?? []) as WatchlistRow[]).map((row) => ({
    ticker: row.ticker,
    companyName: row.company_name,
    disposition: row.disposition,
    addedAt: row.added_at,
    updatedAt: row.updated_at,
  }));
}
