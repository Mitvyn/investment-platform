import type { MoomooDesktopHoldings } from "@/lib/moomoo-desktop";

function formatDecimal(value: string) {
  const [whole, fraction] = value.split(".");
  const sign = whole.startsWith("-") ? "-" : "";
  const digits = sign ? whole.slice(1) : whole;
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${sign}${grouped}${fraction === undefined ? "" : `.${fraction}`}`;
}

function formatMoney(value: string, currency: string) {
  return `${currency} ${formatDecimal(value)}`;
}

export function MoomooHoldingsTable({
  holdings,
}: {
  holdings: MoomooDesktopHoldings;
}) {
  return (
    <div className="mt-5 overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[760px] text-sm">
        <thead className="bg-muted/35 text-left text-[10px] tracking-[0.1em] text-muted-foreground uppercase">
          <tr>
            <th className="px-4 py-3 font-medium">Security</th>
            <th className="px-4 py-3 text-right font-medium">Quantity</th>
            <th className="px-4 py-3 text-right font-medium">Cost</th>
            <th className="px-4 py-3 text-right font-medium">Market price</th>
            <th className="px-4 py-3 text-right font-medium">Market value</th>
            <th className="px-4 py-3 text-right font-medium">Unrealized P/L</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {holdings.positions.map((position) => (
            <tr key={`${position.accountIndex}:${position.code}:${position.positionSide}`}>
              <td className="px-4 py-3">
                <div className="font-mono font-medium text-foreground">
                  {position.canonicalTicker ?? position.code}
                </div>
                <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                  <span>{position.stockName}</span>
                  {position.mappingState && position.mappingState !== "mapped" ? (
                    <span className="rounded border border-warning/40 px-1.5 py-0.5 text-[10px] text-warning uppercase">
                      {position.mappingState}
                    </span>
                  ) : null}
                </div>
              </td>
              <td className="px-4 py-3 text-right font-mono tabular-nums">
                {formatDecimal(position.quantity)}
              </td>
              <td className="px-4 py-3 text-right font-mono tabular-nums">
                {position.costPriceValid && position.costPrice !== null
                  ? formatMoney(position.costPrice, position.currency)
                  : "Unavailable"}
              </td>
              <td className="px-4 py-3 text-right font-mono tabular-nums">
                {formatMoney(position.nominalPrice, position.currency)}
              </td>
              <td className="px-4 py-3 text-right font-mono tabular-nums">
                {formatMoney(position.marketValue, position.currency)}
              </td>
              <td
                className={`px-4 py-3 text-right font-mono tabular-nums ${
                  position.plValue?.startsWith("-")
                    ? "text-challenge"
                    : "text-foreground"
                }`}
              >
                {position.plValueValid && position.plValue !== null
                  ? formatMoney(position.plValue, position.currency)
                  : "Unavailable"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="border-t border-border px-4 py-2 text-[10px] tracking-wide text-muted-foreground uppercase">
        {holdings.source === "hosted_snapshot"
          ? "Persisted immutable broker snapshot"
          : "Desktop live read-only mirror"}
      </div>
    </div>
  );
}
