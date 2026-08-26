import { ArrowUpRight, CircleAlert, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";

export type ResearchDecisionSummaryStat = {
  detail: string;
  label: string;
  value: string;
  tone?: "default" | "attention" | "verified";
};

export type ResearchAttentionItem = {
  detail: string;
  label: string;
  tone?: "default" | "attention" | "verified";
  value: string;
};

export function ResearchDecisionSummary({
  companyName,
  disposition,
  stats,
  ticker,
  actions,
}: {
  actions?: ReactNode;
  companyName: string;
  disposition: string;
  stats: ResearchDecisionSummaryStat[];
  ticker: string;
}) {
  return (
    <section
      aria-labelledby="research-decision-summary-heading"
      className="mt-5 overflow-hidden rounded-xl border border-border bg-card text-foreground shadow-sm"
    >
      <div className="grid gap-8 p-6 sm:p-8 lg:grid-cols-[minmax(15rem,0.9fr)_minmax(0,1.7fr)] lg:items-end">
        <div>
          <div className="flex items-center gap-2 font-mono text-[10px] font-medium tracking-[0.16em] text-primary uppercase">
            <span className="size-2 rounded-full bg-primary" />
            Decision summary
          </div>
          <h1
            className="mt-4 max-w-xl font-serif text-4xl font-medium tracking-tight sm:text-5xl"
            id="research-decision-summary-heading"
          >
            {ticker}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">{companyName}</p>
          <div className="mt-6 flex flex-wrap items-center gap-2">
            <Badge className="border-border bg-muted text-foreground" variant="outline">
              {disposition}
            </Badge>
            <span className="text-xs text-muted-foreground">
              One ticker workspace · current read and audit trail together
            </span>
          </div>
        </div>

        <dl className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 xl:grid-cols-4">
          {stats.map((stat) => (
            <div className="min-h-28 bg-muted/35 p-4" key={stat.label}>
              <dt className="text-[11px] text-muted-foreground">{stat.label}</dt>
              <dd
                className={`mt-3 font-mono text-xl font-medium tabular-nums ${
                  stat.tone === "attention"
                    ? "text-warning"
                    : stat.tone === "verified"
                      ? "text-primary"
                      : "text-foreground"
                }`}
              >
                {stat.value}
              </dd>
              <dd className="mt-1 text-[11px] leading-4 text-muted-foreground">
                {stat.detail}
              </dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-border px-6 py-3 text-[11px] text-muted-foreground sm:px-8">
        <span className="inline-flex items-center gap-1.5">
          <RefreshCw aria-hidden="true" className="size-3" />
          Evidence freshness is shown explicitly
        </span>
        <span className="inline-flex items-center gap-1.5">
          <CircleAlert aria-hidden="true" className="size-3" />
          Missing data stays visible
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          {actions}
          <a
            className="inline-flex items-center gap-1.5 text-foreground transition-colors hover:text-primary"
            href="#research-details"
          >
            Open details
            <ArrowUpRight aria-hidden="true" className="size-3" />
          </a>
        </div>
      </div>
    </section>
  );
}

export function ResearchDetailsHeading() {
  return (
    <div className="mt-10 flex flex-col gap-2 border-b border-border pb-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <p className="font-mono text-[11px] font-medium tracking-[0.14em] text-primary uppercase">
          Audit and working detail
        </p>
        <h2 className="mt-2 font-serif text-3xl font-medium tracking-tight" id="research-details">
          Research details
        </h2>
      </div>
      <p className="max-w-md text-xs leading-5 text-muted-foreground">
        Evidence, valuation context, opinions, committee synthesis, and thesis
        remain in one scrollable record. Nothing is hidden behind workflow tabs.
      </p>
    </div>
  );
}

export function ResearchAttentionGrid({
  items,
}: {
  items: ResearchAttentionItem[];
}) {
  return (
    <section aria-label="Research summary attention points" className="mt-4 grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <article className="min-h-32 bg-card p-4" key={item.label}>
          <p className="text-[11px] font-medium tracking-[0.08em] text-muted-foreground uppercase">
            {item.label}
          </p>
          <p
            className={`mt-3 break-words font-serif text-xl leading-tight ${
              item.tone === "attention"
                ? "text-warning-muted-foreground"
                : item.tone === "verified"
                  ? "text-evidence"
                  : "text-foreground"
            }`}
          >
            {item.value}
          </p>
          <p className="mt-2 text-xs leading-4 text-muted-foreground">
            {item.detail}
          </p>
        </article>
      ))}
    </section>
  );
}
