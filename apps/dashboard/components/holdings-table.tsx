import type { HoldingSnapshotContext } from "@iros/types";

import type { HoldingsSummary } from "@/lib/holdings-summary";

import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

function formatValue(value: number, currency: string | null) {
  return new Intl.NumberFormat("en-US", {
    ...(currency ? { style: "currency" as const, currency } : {}),
    minimumFractionDigits: 2,
    maximumFractionDigits: 3,
  }).format(value);
}

export function HoldingsTable({
  snapshot,
  summary,
}: {
  snapshot: HoldingSnapshotContext;
  summary: HoldingsSummary;
}) {
  return (
    <Card aria-label="Private holdings" className="mt-5">
      <CardHeader className="gap-4 sm:grid-cols-[1fr_auto] sm:items-start">
        <div>
          <Badge variant="outline">Private portfolio context</Badge>
          <CardTitle className="mt-3">Operator-entered holdings</CardTitle>
          <p className="mt-2 text-sm text-muted-foreground">
            Imported observation · timing {summary.timingLabel} · {summary.currencyLabel}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-x-8 gap-y-1 font-mono text-sm tabular-nums">
          <span className="text-muted-foreground">Observed value</span>
          <strong className="text-right">
            {formatValue(snapshot.totalMarketValue, snapshot.currency)}
          </strong>
          <span className="text-muted-foreground">Unrealized P/L</span>
          <strong
            className={
              snapshot.totalUnrealizedPnl < 0
                ? "text-right text-challenge"
                : "text-right text-foreground"
            }
          >
            {formatValue(snapshot.totalUnrealizedPnl, snapshot.currency)} ·{" "}
            {summary.totalUnrealizedPnlPercent.toFixed(2)}%
          </strong>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="bg-muted/35 text-left text-[10px] tracking-[0.1em] text-muted-foreground uppercase">
              <tr>
                <th className="px-4 py-3 font-medium">Security</th>
                <th className="px-4 py-3 text-right font-medium">Quantity</th>
                <th className="px-4 py-3 text-right font-medium">Average cost</th>
                <th className="px-4 py-3 text-right font-medium">Observed price</th>
                <th className="px-4 py-3 text-right font-medium">Observed value</th>
                <th className="px-4 py-3 text-right font-medium">Unrealized P/L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {summary.positions.map((position) => (
                <tr key={position.positionId}>
                  <td className="px-4 py-3">
                    <a
                      className="font-mono font-medium text-primary hover:underline"
                      href={`/?security=${position.securityId}`}
                    >
                      {position.ticker}
                    </a>
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">
                    {position.quantity}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">
                    {formatValue(position.averageCost, snapshot.currency)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">
                    {formatValue(position.observedPrice, snapshot.currency)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">
                    {formatValue(position.observedMarketValue, snapshot.currency)}
                  </td>
                  <td
                    className={`px-4 py-3 text-right font-mono tabular-nums ${
                      position.unrealizedPnl < 0
                        ? "text-challenge"
                        : "text-foreground"
                    }`}
                  >
                    {formatValue(position.unrealizedPnl, snapshot.currency)} ·{" "}
                    {position.unrealizedPnlPercent.toFixed(2)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
          Private observation only. No Research Committee, readiness, allocation,
          or execution authority.
        </p>
      </CardContent>
    </Card>
  );
}
