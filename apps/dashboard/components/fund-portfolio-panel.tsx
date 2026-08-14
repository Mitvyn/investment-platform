import Link from "next/link";

import type { FundPortfolio, FundSummary } from "@/lib/funds";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">
      {children}
    </p>
  );
}

function signedTone(value: string) {
  return value.startsWith("-") ? "text-destructive" : "text-verified";
}

function formatPercent(value: number | null) {
  if (value === null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function FundSwitcher({
  activeFundKey,
  funds,
  hrefForFund,
}: {
  activeFundKey: string | null;
  funds: FundSummary[];
  hrefForFund: (fundKey: string | null) => string;
}) {
  if (funds.length === 0) return null;
  const items: Array<{ key: string | null; label: string }> = [
    { key: null, label: "All funds" },
    ...funds.map((fund) => ({ key: fund.fundKey, label: fund.label })),
  ];
  return (
    <div
      aria-label="Fund"
      className="flex flex-wrap items-center gap-1"
      role="group"
    >
      {items.map((item) => {
        const current = item.key === activeFundKey;
        return (
          <Link
            aria-current={current ? "true" : undefined}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              current
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
            href={hrefForFund(item.key)}
            key={item.key ?? "all"}
          >
            {item.label}
          </Link>
        );
      })}
    </div>
  );
}

export function AllFundsPanel({
  hrefForFund,
  portfolio,
  unavailableReason,
}: {
  hrefForFund: (fundKey: string | null) => string;
  portfolio: FundPortfolio;
  unavailableReason: string | null;
}) {
  const { funds, total } = portfolio;
  return (
    <Card className="mt-5">
      <CardHeader>
        <SectionLabel>Private portfolio context</SectionLabel>
        <CardTitle className="mt-2">All funds</CardTitle>
      </CardHeader>
      <CardContent>
        {unavailableReason ? (
          <p className="text-sm text-muted-foreground">{unavailableReason}</p>
        ) : funds.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No fund has a complete holdings snapshot yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[42rem] text-left text-sm">
              <caption className="sr-only">
                Latest complete holdings snapshot per fund, with a portfolio
                total. Private observation only.
              </caption>
              <thead className="text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="py-3 pr-4" scope="col">
                    Fund
                  </th>
                  <th className="py-3 pr-4 text-right" scope="col">
                    Positions
                  </th>
                  <th className="py-3 pr-4 text-right" scope="col">
                    Observed value
                  </th>
                  <th className="py-3 pr-4 text-right" scope="col">
                    Cost basis
                  </th>
                  <th className="py-3 text-right" scope="col">
                    Unrealized P/L
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border font-mono tabular-nums">
                {funds.map((fund) => (
                  <tr key={fund.fundKey}>
                    <th className="py-3 pr-4 font-medium" scope="row">
                      <Link
                        className="text-primary hover:underline"
                        href={hrefForFund(fund.fundKey)}
                      >
                        {fund.label}
                      </Link>
                      <span className="ml-2 font-sans text-xs text-muted-foreground">
                        {fund.currencyLabel}
                      </span>
                    </th>
                    <td className="py-3 pr-4 text-right">
                      {fund.positionCount}
                    </td>
                    <td className="py-3 pr-4 text-right">{fund.marketValue}</td>
                    <td className="py-3 pr-4 text-right">{fund.costBasis}</td>
                    <td
                      className={`py-3 text-right ${signedTone(fund.unrealizedPnl)}`}
                    >
                      {fund.unrealizedPnl} ·{" "}
                      {formatPercent(fund.unrealizedPnlPercent)}
                    </td>
                  </tr>
                ))}
              </tbody>
              {total ? (
                <tfoot className="border-t-2 border-border font-mono tabular-nums">
                  <tr>
                    <th className="py-3 pr-4 text-left font-medium" scope="row">
                      Total
                      <span className="ml-2 font-sans text-xs text-muted-foreground">
                        {total.currencyLabel}
                      </span>
                    </th>
                    <td className="py-3 pr-4" />
                    <td className="py-3 pr-4 text-right">
                      {total.mixedCurrency ? "—" : total.marketValue}
                    </td>
                    <td className="py-3 pr-4 text-right">
                      {total.mixedCurrency ? "—" : total.costBasis}
                    </td>
                    <td
                      className={`py-3 text-right ${
                        total.mixedCurrency ? "" : signedTone(total.unrealizedPnl)
                      }`}
                    >
                      {total.mixedCurrency
                        ? "—"
                        : `${total.unrealizedPnl} · ${formatPercent(total.unrealizedPnlPercent)}`}
                    </td>
                  </tr>
                </tfoot>
              ) : null}
            </table>
            {total?.mixedCurrency ? (
              <p className="mt-3 text-xs text-muted-foreground">
                Funds report different currencies. No combined total is shown
                because summing across currencies would not be true in any of
                them.
              </p>
            ) : null}
          </div>
        )}
        <p className="mt-4 text-xs text-muted-foreground">
          Private observation only. No Research Committee, readiness,
          allocation, or execution authority.
        </p>
      </CardContent>
    </Card>
  );
}
