import type { SecurityDirectoryItem } from "@iros/types";

import { createClient } from "./supabase/server";

type SecurityRow = {
  id: string;
  cik: string;
  symbol: string;
  issuer_name: string;
  primary_listing_exchange: string;
};

export async function loadSecurityDirectory(): Promise<SecurityDirectoryItem[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_securities")
    .select("id,cik,symbol,issuer_name,primary_listing_exchange")
    .order("symbol", { ascending: true });

  if (error) {
    throw new Error(`Security directory API failed: ${error.message}`);
  }

  return ((data ?? []) as SecurityRow[]).map((row) => ({
    securityId: row.id,
    cik: row.cik,
    ticker: row.symbol,
    companyName: row.issuer_name,
    primaryListingExchange: row.primary_listing_exchange,
  }));
}
