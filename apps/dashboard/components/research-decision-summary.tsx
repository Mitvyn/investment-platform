import { ArrowUpRight, CircleAlert, RefreshCw } from "lucide-react";

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
}: {
  companyName: string;
  disposition: string;
  stats: ResearchDecisionSummaryStat[];
  ticker: string;
}) {
  return (
    <section
      aria-labelledby="research-decision-summary-heading"
      className="mt-5 overflow-hidden rounded-xl border border-foreground/10 bg-foreground text-background shadow-sm"
    >
      <div className="grid gap-8 p-6 sm:p-8 lg:grid-cols-[minmax(15rem,0.9fr)_minmax(0,1.7fr)] lg:items-end">
        <div>
          <div className="flex items-center gap-2 font-mono text-[10px] font-medium tracking-[0.16em] text-background/60 uppercase">
            <span className="size-2 rounded-full bg-primary" />
            Decision summary
          </div>
          <h1
            className="mt-4 max-w-xl font-serif text-4xl font-medium tracking-tight sm:text-5xl"
            id="research-decision-summary-heading"
          >
            {ticker}
          </h1>
          <p className="mt-2 text-sm text-background/65">{companyName}</p>
          <div className="mt-6 flex flex-wrap items-center gap-2">
            <Badge className="border-background/20 bg-background/10 text-background" variant="outline">
              {disposition}
            </Badge>
            <span className="text-xs text-background/55">
              One ticker workspace · current read and audit trail together
            </span>
          </div>
        </div>

        <dl className="grid gap-px overflow-hidden rounded-lg border border-background/15 bg-background/15 sm:grid-cols-2 xl:grid-cols-4">
          {stats.map((stat) => (
            <div className="min-h-28 bg-background/[0.06] p-4" key={stat.label}>
              <dt className="text-[11px] text-background/55">{stat.label}</dt>
              <dd
                className={`mt-3 font-mono text-xl font-medium tabular-nums ${
                  stat.tone === "attention"
                    ? "text-warning"
                    : stat.tone === "verified"
                      ? "text-primary"
                      : "text-background"
                }`}
              >
                {stat.value}
              </dd>
              <dd className="mt-1 text-[11px] leading-4 text-background/55">
                {stat.detail}
              </dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-background/10 px-6 py-3 text-[11px] text-background/55 sm:px-8">
        <span className="inline-flex items-center gap-1.5">
          <RefreshCw aria-hidden="true" className="size-3" />
          Evidence freshness is shown explicitly
        </span>
        <span className="inline-flex items-center gap-1.5">
          <CircleAlert aria-hidden="true" className="size-3" />
          Missing data stays visible
        </span>
        <a
          className="ml-auto inline-flex items-center gap-1.5 text-background transition-colors hover:text-primary"
          href="#research-details"
        >
          Open details
          <ArrowUpRight aria-hidden="true" className="size-3" />
        </a>
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
            className={`mt-3 line-clamp-2 font-serif text-xl leading-tight ${
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
