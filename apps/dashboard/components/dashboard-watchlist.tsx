import Link from "next/link";
import { ArrowUpRight, Radar } from "lucide-react";

import type { WatchlistItem } from "@iros/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Watchlist as a Dashboard shortcut rail. Each entry opens that security's
 * Research Run rather than a separate security screen, so the daily path from
 * "I am watching this" to "show me the run" is one click.
 */
export function DashboardWatchlist({
  hrefForSecurity,
  items,
}: {
  hrefForSecurity: (securityId: string) => string;
  items: WatchlistItem[];
}) {
  return (
    <Card className="mt-5">
      <CardHeader>
        <p className="font-mono text-[11px] font-medium tracking-[0.14em] text-primary uppercase">
          Watchlist
        </p>
        <CardTitle className="mt-2">Monitored securities</CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No monitored securities. Open a security in Research and choose
            Monitor to add it here.
          </p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {items
              .filter((item) => item.securityId !== null)
              .map((item) => (
              <li key={item.securityId}>
                <Link
                  className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted"
                  href={hrefForSecurity(item.securityId as string)}
                >
                  <Radar
                    aria-hidden="true"
                    className="size-3.5 text-primary"
                  />
                  <span className="font-mono font-medium">{item.ticker}</span>
                  <ArrowUpRight
                    aria-hidden="true"
                    className="size-3.5 text-muted-foreground"
                  />
                  <span className="sr-only">Open Research Run</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
