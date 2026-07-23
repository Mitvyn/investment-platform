import type { WatchlistItem } from "@iros/types";

export type WatchlistRow = {
  security_id: string | null;
  ticker: string;
  company_name: string;
  disposition: WatchlistItem["disposition"];
  added_at: string;
  updated_at: string;
};

export type WatchlistSecurityRow = {
  id: string;
  symbol: string;
  issuer_name: string;
};

export function resolveWatchlistRows(
  rows: WatchlistRow[],
  securities: WatchlistSecurityRow[],
): WatchlistItem[] {
  const securitiesById = new Map(securities.map((security) => [security.id, security]));
  const securitiesBySymbol = new Map<string, WatchlistSecurityRow | null>();
  for (const security of securities) {
    securitiesBySymbol.set(
      security.symbol,
      securitiesBySymbol.has(security.symbol) ? null : security,
    );
  }

  const resolved = new Map<string, WatchlistItem>();
  const orderedRows = [
    ...rows.filter((row) => row.security_id !== null),
    ...rows.filter((row) => row.security_id === null),
  ];
  for (const row of orderedRows) {
    const security = row.security_id
      ? securitiesById.get(row.security_id)
      : securitiesBySymbol.get(row.ticker);
    if (!security || resolved.has(security.id)) continue;

    resolved.set(security.id, {
      securityId: security.id,
      ticker: security.symbol,
      companyName: security.issuer_name,
      disposition: row.disposition,
      addedAt: row.added_at,
      updatedAt: row.updated_at,
    });
  }

  return [...resolved.values()].sort((left, right) =>
    right.updatedAt.localeCompare(left.updatedAt),
  );
}
