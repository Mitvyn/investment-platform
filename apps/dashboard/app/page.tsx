import type { FinancialMetric } from "@iros/types";
import {
  Activity,
  ArrowUpRight,
  BookOpenCheck,
  ChevronDown,
  Cpu,
  Database,
  FileText,
  FlaskConical,
  LogOut,
  Radar,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MarketPriceChart } from "@/components/market-price-chart";
import { HoldingsTable } from "@/components/holdings-table";
import { WorkflowJobPoller } from "@/components/workflow-job-poller";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import {
  dashboardSections,
  isDashboardSectionAvailable,
} from "@/lib/dashboard-shell";
import { readDesktopRuntimeStatus } from "@/lib/desktop-runtime";
import { summarizeMarketSeries } from "@/lib/market-series";
import { summarizeHoldings } from "@/lib/holdings-summary";

import { loadMarketSeries, loadTickerContext } from "../lib/context";
import { loadEvidenceTrace } from "../lib/evidence";
import { loadLatestHoldings } from "../lib/holdings";
import { loadResearchRunCommand } from "../lib/research-run-commands";
import { loadSecurityDirectory } from "../lib/securities";
import { loadSecurityJob } from "../lib/security-jobs";
import { createClient } from "../lib/supabase/server";
import { loadWatchlist } from "../lib/watchlist";
import { signOut, toggleWatchlist } from "./actions";
import { launchResearchRun } from "./research-actions";
import { registerSecurity } from "./security-actions";

export const dynamic = "force-dynamic";

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

function formatMetric(metric: FinancialMetric) {
  if (metric.unit === "USD_millions") return `$${metric.value.toFixed(1)}m`;
  if (metric.unit === "percent") {
    return `${metric.value > 0 ? "+" : ""}${metric.value.toFixed(2)}%`;
  }
  return `${metric.value.toFixed(2)} qtrs`;
}

function formatCurrency(value: number, currency: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: value < 1 ? 4 : 2,
  }).format(value);
}

function formatVolume(value: number | null) {
  if (value === null) return "Unavailable";
  return new Intl.NumberFormat("en-US", { notation: "compact" }).format(value);
}

function ageLabel(value: string) {
  const elapsedHours = Math.max(
    0,
    Math.floor((Date.now() - new Date(value).getTime()) / 3_600_000),
  );
  if (elapsedHours < 1) return "under 1h old";
  if (elapsedHours < 48) return `${elapsedHours}h old`;
  return `${Math.floor(elapsedHours / 24)}d old`;
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-[11px] font-medium tracking-[0.14em] text-primary uppercase">
      {children}
    </p>
  );
}

function DataList({
  items,
}: {
  items: Array<{ label: string; value: ReactNode }>;
}) {
  return (
    <dl className="grid gap-4 sm:grid-cols-3">
      {items.map((item) => (
        <div className="border-t border-border pt-3" key={item.label}>
          <dt className="text-[10px] font-medium tracking-[0.1em] text-muted-foreground uppercase">
            {item.label}
          </dt>
          <dd className="mt-1.5 break-words font-mono text-xs text-foreground">
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function SourceLink({ href, label }: { href: string; label: string }) {
  return (
    <Button asChild className="mt-5 px-0" variant="link">
      <a
        aria-label={`${label} (opens in new tab)`}
        href={href}
        rel="noreferrer"
        target="_blank"
      >
        {label}
        <ArrowUpRight aria-hidden="true" />
      </a>
    </Button>
  );
}

function SourceHealth({
  available,
  detail,
  gated = false,
  icon,
  label,
}: {
  available: boolean;
  detail: string;
  gated?: boolean;
  icon: ReactNode;
  label: string;
}) {
  let variant: "verified" | "attention" | "destructive" = "destructive";
  let stateClassName = "text-challenge";
  let stateLabel = "Missing";

  if (available) {
    variant = "verified";
    stateClassName = "text-evidence";
    stateLabel = "Ready";
  } else if (gated) {
    variant = "attention";
    stateClassName = "text-warning";
    stateLabel = "Gated";
  }

  return (
    <div className="flex min-h-20 items-center gap-3 px-4 py-3">
      <span className={stateClassName}>
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <strong className="text-sm font-medium">{label}</strong>
          <Badge variant={variant}>{stateLabel}</Badge>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
      </div>
    </div>
  );
}

export default async function TickerWorkspace({
  searchParams,
}: {
  searchParams: Promise<{
    registration?: string;
    registration_error?: string;
    research_command?: string;
    research_error?: string;
    security?: string;
  }>;
}) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  if (error || !data?.claims) redirect("/login");

  const params = await searchParams;
  const requestedSecurityId = params.security;
  const operatorId = String(data.claims.sub ?? "");
  const registrationJob = params.registration
    ? await loadSecurityJob(operatorId, params.registration)
    : null;
  const [securities, watchlist, holdingsResult] = await Promise.all([
    loadSecurityDirectory(),
    loadWatchlist(),
    loadLatestHoldings(),
  ]);
  const selectedSecurity =
    securities.find((security) => security.securityId === requestedSecurityId) ??
    securities[0] ??
    null;
  const researchCommand = params.research_command
    ? await loadResearchRunCommand(operatorId, params.research_command)
    : null;
  const visibleResearchCommand =
    researchCommand?.security_id === selectedSecurity?.securityId
      ? researchCommand
      : null;
  const defaultCutoff = new Date().toISOString().slice(0, 16);
  const ticker = selectedSecurity?.ticker ?? "";
  const displayTicker = ticker || "SELECT";
  const [{ trace }, context, marketSeriesResult] = await Promise.all([
    selectedSecurity
      ? loadEvidenceTrace(selectedSecurity.securityId)
      : Promise.resolve({ trace: null }),
    selectedSecurity
      ? loadTickerContext(selectedSecurity.securityId)
      : Promise.resolve({
          financialMetrics: [],
          catalyst: null,
          risk: null,
          market: null,
          marketSeries: null,
        }),
    selectedSecurity
      ? loadMarketSeries(selectedSecurity.securityId)
      : Promise.resolve({ series: null, unavailableReason: null }),
  ]);
  const marketSeries = marketSeriesResult.series;
  const holdingsSummary = holdingsResult.snapshot
    ? summarizeHoldings(holdingsResult.snapshot)
    : null;
  const summary = marketSeries
    ? summarizeMarketSeries(marketSeries.bars)
    : null;
  const issuerRetrievedAt = context.financialMetrics[0]?.retrievedAt;
  const hasResearch = Boolean(
    trace ||
      context.financialMetrics.length ||
      context.catalyst ||
      context.risk ||
      context.market ||
      marketSeries,
  );
  const sourceCount = Number(Boolean(trace)) + Number(Boolean(issuerRetrievedAt));
  const isWatched = watchlist.some(
    (item) => item.securityId === selectedSecurity?.securityId,
  );
  const desktopRuntime = readDesktopRuntimeStatus();

  return (
    <div className="min-h-screen bg-background lg:grid lg:grid-cols-[264px_minmax(0,1fr)]">
      <aside className="hidden border-r border-sidebar-border bg-sidebar text-sidebar-foreground lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col">
        <div className="border-b border-sidebar-border px-6 py-6">
          <div className="flex items-center gap-3">
            <span className="grid size-9 place-items-center rounded-lg bg-sidebar-primary font-mono text-xs font-semibold text-sidebar-primary-foreground">
              IR
            </span>
            <div>
              <p className="text-sm font-semibold">Research OS</p>
              <p className="text-xs text-muted-foreground">Auditable research desk</p>
            </div>
          </div>
        </div>
        <nav aria-label="Research workspace" className="grid gap-1 p-3">
          {dashboardSections.map((section) => {
            const current = section === "overview";
            const available = isDashboardSectionAvailable(section);
            const label = section.charAt(0).toUpperCase() + section.slice(1);

            if (!available) {
              return (
                <span
                  aria-disabled="true"
                  className="flex cursor-not-allowed items-center justify-between border-l-2 border-transparent px-3 py-2.5 text-sm text-muted-foreground/55"
                  key={section}
                >
                  {label}
                  <span className="font-mono text-[9px] tracking-wide uppercase">
                    Planned
                  </span>
                </span>
              );
            }

            return (
              <a
                aria-current={current ? "page" : undefined}
                className={
                  current
                    ? "border-l-2 border-sidebar-primary bg-sidebar-accent px-3 py-2.5 text-sm font-medium text-sidebar-accent-foreground"
                    : "border-l-2 border-transparent px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
                }
                href={`#${section}`}
                key={section}
              >
                {label}
              </a>
            );
          })}
        </nav>
        <div className="mt-auto border-t border-sidebar-border p-3">
          <form action={signOut}>
            <Button className="w-full justify-start" type="submit" variant="ghost">
              <LogOut aria-hidden="true" />
              Sign out
            </Button>
          </form>
        </div>
      </aside>

      <main className="min-w-0 px-4 pb-16 sm:px-6 lg:px-8">
        <header className="flex min-h-16 items-center justify-between border-b border-border">
          <div className="flex items-center gap-3 lg:hidden">
            <span className="grid size-8 place-items-center rounded-md bg-primary font-mono text-[10px] font-semibold text-primary-foreground">
              IR
            </span>
            <span className="text-sm font-semibold">Research OS</span>
          </div>
          <Badge className="ml-auto" variant="outline">
            Authenticated research ledger
          </Badge>
          <form action={signOut} className="ml-2 lg:hidden">
            <Button aria-label="Sign out" size="icon" type="submit" variant="ghost">
              <LogOut aria-hidden="true" />
            </Button>
          </form>
        </header>

        <div className="mx-auto max-w-[1480px]">
          <Card className="mt-5">
            <CardContent className="grid gap-6 pt-5 sm:pt-6 lg:grid-cols-2">
              <form className="flex flex-1 flex-col gap-2 sm:max-w-lg" method="get">
                <label
                  className="text-xs font-medium text-muted-foreground"
                  htmlFor="security"
                >
                  Registered security
                </label>
                <div className="flex gap-2">
                  <div className="relative h-9 min-w-0 flex-1">
                    <select
                      className="block h-9 w-full appearance-none rounded-md border border-input bg-background py-0 pr-10 pl-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40"
                      defaultValue={selectedSecurity?.securityId ?? ""}
                      id="security"
                      name="security"
                    >
                      {securities.length ? (
                        securities.map((security) => (
                          <option key={security.securityId} value={security.securityId}>
                            {security.ticker} · {security.companyName}
                          </option>
                        ))
                      ) : (
                        <option value="">No registered securities</option>
                      )}
                    </select>
                    <ChevronDown
                      aria-hidden="true"
                      className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                    />
                  </div>
                  <Button disabled={!securities.length} type="submit" variant="outline">
                    Open
                  </Button>
                </div>
              </form>
              <form action={registerSecurity} className="flex flex-col gap-2">
                <label
                  className="text-xs font-medium text-muted-foreground"
                  htmlFor="ticker"
                >
                  Add security
                </label>
                <div className="flex gap-2">
                  <Input
                    autoCapitalize="characters"
                    autoComplete="off"
                    className="h-9 font-mono uppercase"
                    id="ticker"
                    maxLength={10}
                    name="ticker"
                    pattern="[A-Za-z][A-Za-z0-9.-]{0,9}"
                    placeholder="CRSP"
                    required
                  />
                  <Button type="submit">Add security</Button>
                </div>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Resolves SEC issuer identity, then queues private market context.
                  Registration does not grant biotech eligibility.
                </p>
              </form>
            </CardContent>
          </Card>
          {params.registration_error ? (
            <Card className="mt-5 border-challenge/35 bg-challenge-muted">
              <CardContent className="py-4 text-sm text-challenge-muted-foreground">
                {params.registration_error === "invalid_ticker"
                  ? "Enter a valid US ticker using letters, numbers, dots, or hyphens."
                  : "Security onboarding could not be queued. Retry after checking service status."}
              </CardContent>
            </Card>
          ) : null}
          {registrationJob ? (
            <Card className="mt-5" aria-live="polite">
              <CardContent className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-semibold">
                      {registrationJob.ticker}
                    </span>
                    <Badge
                      variant={
                        registrationJob.state === "completed"
                          ? "verified"
                          : registrationJob.state === "failed"
                            ? "destructive"
                            : "default"
                      }
                    >
                      {registrationJob.state}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {registrationJob.state === "queued"
                      ? "Waiting for security worker."
                      : registrationJob.state === "running"
                        ? "Resolving SEC identity and persisted market context."
                        : registrationJob.state === "completed"
                          ? "Canonical security ready. Opening workspace."
                          : `Onboarding stopped: ${registrationJob.error_code ?? "unknown_error"}. Submit the ticker again to start a new bounded attempt.`}
                  </p>
                </div>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {registrationJob.job_id}
                </span>
                <WorkflowJobPoller
                  key={registrationJob.job_id}
                  securityId={registrationJob.security_id}
                  state={registrationJob.state}
                />
              </CardContent>
            </Card>
          ) : null}
          {selectedSecurity ? (
            <Card className="mt-5">
              <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <SectionLabel>Research Run preflight</SectionLabel>
                    <CardTitle className="mt-2">
                      Launch the fixed biotech committee contract
                    </CardTitle>
                  </div>
                  <Badge variant="outline">
                    biotech_moonshot_catalyst_assessment
                  </Badge>
                </div>
                <CardDescription>
                  This early tracer persists and validates a command only. Current
                  production gates block evidence, market, and model execution.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form
                  action={launchResearchRun}
                  className="grid gap-4 lg:grid-cols-[minmax(0,240px)_minmax(0,1fr)_auto] lg:items-end"
                >
                  <input
                    name="securityId"
                    type="hidden"
                    value={selectedSecurity.securityId}
                  />
                  <div className="grid gap-2">
                    <label
                      className="text-xs font-medium text-muted-foreground"
                      htmlFor="asOfCutoff"
                    >
                      Evidence cutoff (UTC)
                    </label>
                    <Input
                      defaultValue={defaultCutoff}
                      id="asOfCutoff"
                      max={defaultCutoff}
                      name="asOfCutoff"
                      required
                      type="datetime-local"
                    />
                  </div>
                  <div className="grid gap-2">
                    <label
                      className="text-xs font-medium text-muted-foreground"
                      htmlFor="operatorFocus"
                    >
                      Optional research emphasis
                    </label>
                    <textarea
                      className="min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40"
                      id="operatorFocus"
                      maxLength={2000}
                      name="operatorFocus"
                      placeholder="Focus on financing through the next catalyst."
                    />
                  </div>
                  <Button type="submit">Run preflight</Button>
                </form>
                <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1 border-t border-border pt-4 font-mono text-[10px] text-muted-foreground">
                  <span>question v1</span>
                  <span>workflow biotech-moonshot-catalyst-v1</span>
                  <span>security {selectedSecurity.securityId}</span>
                </div>
              </CardContent>
            </Card>
          ) : null}
          {params.research_error ? (
            <Card className="mt-5 border-challenge/35 bg-challenge-muted">
              <CardContent className="py-4 text-sm text-challenge-muted-foreground">
                {params.research_error === "invalid_request"
                  ? "Research Run request is invalid. Check the UTC cutoff and bounded research emphasis."
                  : "Research Run preflight could not be persisted. Retry after checking service status."}
              </CardContent>
            </Card>
          ) : null}
          {visibleResearchCommand ? (
            <Card className="mt-5" aria-live="polite">
              <CardHeader>
                <div className="flex flex-wrap items-center gap-2">
                  <CardTitle>
                    {visibleResearchCommand.state === "blocked"
                      ? "Launch blocked"
                      : `Research command ${visibleResearchCommand.state}`}
                  </CardTitle>
                  <Badge
                    variant={
                      visibleResearchCommand.state === "completed"
                        ? "verified"
                        : visibleResearchCommand.state === "failed"
                          ? "destructive"
                          : "attention"
                    }
                  >
                    {visibleResearchCommand.state}
                  </Badge>
                </div>
                <CardDescription>
                  {visibleResearchCommand.state === "blocked"
                    ? "No evidence, market, or model execution was started."
                    : "Command state is persisted in the authenticated research ledger."}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {visibleResearchCommand.blocking_reason_codes.length ? (
                  <ul className="grid gap-2 sm:grid-cols-2">
                    {visibleResearchCommand.blocking_reason_codes.map((reason) => (
                      <li
                        className="rounded-md border border-border bg-muted/35 px-3 py-2 font-mono text-xs"
                        key={reason}
                      >
                        {reason}
                      </li>
                    ))}
                  </ul>
                ) : null}
                <DataList
                  items={[
                    {
                      label: "Command",
                      value: visibleResearchCommand.command_id,
                    },
                    {
                      label: "Cutoff",
                      value: visibleResearchCommand.as_of_cutoff,
                    },
                    {
                      label: "Updated",
                      value: visibleResearchCommand.updated_at,
                    },
                  ]}
                />
                {visibleResearchCommand.state === "completed" &&
                visibleResearchCommand.research_run_id ? (
                  <Button asChild className="mt-5">
                    <a
                      href={`/research-runs/${visibleResearchCommand.research_run_id}`}
                    >
                      Open Research Run audit
                    </a>
                  </Button>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
          {holdingsResult.snapshot && holdingsSummary ? (
            <HoldingsTable
              snapshot={holdingsResult.snapshot}
              summary={holdingsSummary}
            />
          ) : (
            <Card className="mt-5">
              <CardHeader>
                <SectionLabel>Private holdings</SectionLabel>
                <CardTitle className="mt-2">No registered holdings snapshot</CardTitle>
                <CardDescription>
                  {holdingsResult.unavailableReason ??
                    "Import one operator-entered snapshot after canonical securities exist."}
                </CardDescription>
              </CardHeader>
            </Card>
          )}
          {!hasResearch ? (
            <Card className="mt-12">
              <CardHeader className="max-w-3xl py-12 sm:py-16">
                <SectionLabel>Hosted research spine ready</SectionLabel>
                <CardTitle className="mt-5 font-mono text-6xl tracking-[-0.08em] sm:text-8xl">
                  {displayTicker}
                </CardTitle>
                <CardDescription className="mt-4 text-base">
                  No hosted research context yet. Ingest SEC filing and official
                  issuer release after operator identity is available.
                </CardDescription>
              </CardHeader>
            </Card>
          ) : (
            <>
              <section
                className="grid gap-8 border-b border-border py-10 sm:py-14 lg:grid-cols-[1fr_auto] lg:items-end"
                id="overview"
              >
                <div>
                  <SectionLabel>Evidence-backed ticker workspace</SectionLabel>
                  <h1 className="mt-5 font-mono text-7xl font-medium tracking-[-0.08em] sm:text-9xl">
                    {displayTicker}
                  </h1>
                  <p className="mt-4 text-lg text-muted-foreground">
                    {trace?.companyName ??
                      selectedSecurity?.companyName ??
                      displayTicker}
                  </p>
                </div>
                <Card className="min-w-64 border-primary/35">
                  <CardContent className="pt-5 sm:pt-6">
                    <p className="text-xs text-muted-foreground">Primary source classes</p>
                    <p className="mt-2 font-mono text-4xl font-medium text-primary">
                      {sourceCount} / 2
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      SEC filing + issuer release
                    </p>
                  </CardContent>
                </Card>
              </section>

              <Card className="my-5">
                <CardContent className="flex flex-col gap-4 pt-5 sm:flex-row sm:items-center sm:justify-between sm:pt-6">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="mr-2 text-xs font-medium text-muted-foreground">
                      Watchlist
                    </span>
                    {watchlist.length ? (
                      watchlist.map((item) =>
                        item.securityId ? (
                          <Button asChild key={item.securityId} size="sm" variant="outline">
                            <a href={`/?security=${item.securityId}`}>
                              {item.ticker} · {item.disposition.replace("_", " ")}
                            </a>
                          </Button>
                        ) : (
                          <Badge key={item.ticker} variant="secondary">
                            {item.ticker} · {item.disposition.replace("_", " ")}
                          </Badge>
                        ),
                      )
                    ) : (
                      <span className="text-sm text-muted-foreground">
                        No monitored tickers
                      </span>
                    )}
                  </div>
                  {selectedSecurity ? (
                    <form action={toggleWatchlist}>
                      <input
                        name="securityId"
                        type="hidden"
                        value={selectedSecurity.securityId}
                      />
                      <Button type="submit" variant="outline">
                        <Radar aria-hidden="true" />
                        {isWatched ? `Remove ${ticker}` : `Monitor ${ticker}`}
                      </Button>
                    </form>
                  ) : null}
                </CardContent>
              </Card>

              <Card aria-label="Source health">
                <div className="grid divide-y divide-border lg:grid-cols-4 lg:divide-x lg:divide-y-0">
                  <SourceHealth
                    available={Boolean(trace)}
                    detail={trace ? `Retrieved ${ageLabel(trace.retrievedAt)}` : "Missing"}
                    icon={<FileText aria-hidden="true" className="size-5" />}
                    label="SEC filing"
                  />
                  <SourceHealth
                    available={Boolean(issuerRetrievedAt)}
                    detail={
                      issuerRetrievedAt
                        ? `Retrieved ${ageLabel(issuerRetrievedAt)}`
                        : "Missing"
                    }
                    icon={<BookOpenCheck aria-hidden="true" className="size-5" />}
                    label="Issuer release"
                  />
                  <SourceHealth
                    available={Boolean(marketSeries || context.market)}
                    detail={
                      marketSeries
                        ? `${marketSeries.bars.length} completed sessions · retrieved ${ageLabel(marketSeries.retrievedAt)}`
                        : context.market
                          ? `Retrieved ${ageLabel(context.market.retrievedAt)}`
                          : marketSeriesResult.unavailableReason ??
                            "Personal-use feed unavailable"
                    }
                    gated={!marketSeries && !context.market}
                    icon={<Activity aria-hidden="true" className="size-5" />}
                    label="Market OHLCV"
                  />
                  <SourceHealth
                    available={desktopRuntime.state === "ready"}
                    detail={desktopRuntime.detail}
                    gated={desktopRuntime.state === "unavailable"}
                    icon={<Cpu aria-hidden="true" className="size-5" />}
                    label="Desktop runtime"
                  />
                </div>
              </Card>

              <section
                aria-label="Ticker context"
                className="grid gap-5 py-5 xl:grid-cols-12"
              >
                <Card className="xl:col-span-5">
                  <CardHeader>
                    <SectionLabel>Market context</SectionLabel>
                    <CardTitle>Point-in-time market view</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {summary && marketSeries ? (
                      <>
                        <p className="font-mono text-5xl font-medium tracking-tight tabular-nums">
                          {formatCurrency(summary.latest.close, marketSeries.currency)}
                        </p>
                        <p
                          className={`mt-2 font-mono text-sm tabular-nums ${summary.change >= 0 ? "text-evidence" : "text-challenge"}`}
                        >
                          {summary.change >= 0 ? "+" : ""}
                          {summary.change.toFixed(2)} ({summary.percentChange.toFixed(2)}%)
                        </p>
                        <div className="mt-8">
                          <DataList
                            items={[
                              {
                                label: "Open",
                                value: formatCurrency(
                                  summary.latest.open,
                                  marketSeries.currency,
                                ),
                              },
                              {
                                label: "Session high",
                                value: formatCurrency(
                                  summary.latest.high,
                                  marketSeries.currency,
                                ),
                              },
                              {
                                label: "Session low",
                                value: formatCurrency(
                                  summary.latest.low,
                                  marketSeries.currency,
                                ),
                              },
                              {
                                label: "Previous close",
                                value: formatCurrency(
                                  summary.previousClose,
                                  marketSeries.currency,
                                ),
                              },
                              {
                                label: "Volume",
                                value: formatVolume(summary.latest.volume),
                              },
                              {
                                label: "20-session avg volume",
                                value: formatVolume(summary.averageVolume20),
                              },
                              {
                                label: "Relative volume",
                                value:
                                  summary.relativeVolume20 === null
                                    ? "Needs 20 complete sessions"
                                    : `${summary.relativeVolume20.toFixed(2)}×`,
                              },
                              {
                                label: "Observed high",
                                value: formatCurrency(
                                  summary.periodHigh,
                                  marketSeries.currency,
                                ),
                              },
                              {
                                label: "Observed low",
                                value: formatCurrency(
                                  summary.periodLow,
                                  marketSeries.currency,
                                ),
                              },
                            ]}
                          />
                        </div>
                        <p className="mt-5 text-xs leading-relaxed text-muted-foreground">
                          Yahoo Finance via yfinance · unofficial personal-use
                          context · unadjusted completed daily sessions · not
                          valuation or readiness evidence
                        </p>
                      </>
                    ) : context.market ? (
                      <>
                        <p className="font-mono text-5xl font-medium tracking-tight tabular-nums">
                          {new Intl.NumberFormat("en-US", {
                            style: "currency",
                            currency: context.market.currency,
                          }).format(context.market.close)}
                        </p>
                        <p className="mt-2 font-mono text-sm tabular-nums text-primary">
                          {context.market.change >= 0 ? "+" : ""}
                          {context.market.change.toFixed(2)} (
                          {context.market.percentChange.toFixed(2)}%)
                        </p>
                        <div className="mt-8">
                          <DataList
                            items={[
                              { label: "Venue", value: context.market.exchange },
                              { label: "As of", value: formatDate(context.market.marketTime) },
                              {
                                label: "Market",
                                value: context.market.isMarketOpen ? "Open" : "Closed",
                              },
                            ]}
                          />
                        </div>
                        <p className="mt-5 text-xs text-muted-foreground">
                          {context.market.provider ===
                          "yahoo_finance_via_yfinance"
                            ? "Yahoo Finance via yfinance · unofficial personal-use data"
                            : "Legacy Twelve Data snapshot"}
                        </p>
                      </>
                    ) : (
                      <div className="py-6">
                        <Badge variant="attention">Feed unavailable</Badge>
                        <h2 className="mt-5 font-serif text-3xl">
                          No personal market snapshot available.
                        </h2>
                        <p className="mt-3 max-w-lg text-sm leading-relaxed text-muted-foreground">
                          Ingest through the server-side yfinance worker; the
                          dashboard never calls Yahoo Finance directly.
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card className="xl:col-span-7 xl:row-span-2">
                  <CardHeader className="sm:grid-cols-[1fr_auto] sm:items-start">
                    <div>
                      <SectionLabel>Financial health</SectionLabel>
                      <CardTitle className="mt-2">
                        Reported facts and transparent arithmetic
                      </CardTitle>
                    </div>
                    {issuerRetrievedAt ? (
                      <Badge variant="outline">
                        Published {formatDate(context.financialMetrics[0].publishedAt)}
                      </Badge>
                    ) : null}
                  </CardHeader>
                  <CardContent>
                    {context.financialMetrics.length ? (
                      <div className="grid overflow-hidden rounded-lg border border-border sm:grid-cols-2">
                        {context.financialMetrics.map((metric) => (
                          <div
                            className="flex min-h-48 flex-col border-border p-5 odd:border-b sm:odd:border-r sm:[&:not(:nth-last-child(-n+2))]:border-b"
                            key={metric.metricKey}
                          >
                            <span className="text-sm text-muted-foreground">
                              {metric.metricLabel}
                            </span>
                            <strong className="mt-5 font-mono text-3xl font-medium tracking-tight tabular-nums sm:text-4xl">
                              {formatMetric(metric)}
                            </strong>
                            <small className="mt-2 text-xs text-muted-foreground">
                              {metric.sourcePeriod}
                            </small>
                            <code className="mt-auto pt-6 font-mono text-[10px] leading-relaxed text-evidence">
                              {metric.formula ?? "Reported by issuer"}
                            </code>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        No issuer financial metrics ingested.
                      </p>
                    )}
                    {context.financialMetrics[0] ? (
                      <SourceLink
                        href={context.financialMetrics[0].sourceUrl}
                        label="Open issuer release"
                      />
                    ) : null}
                  </CardContent>
                </Card>

                <Card className="border-primary/30 xl:col-span-5">
                  <CardHeader>
                    <div className="flex items-center justify-between gap-3">
                      <SectionLabel>Forward catalyst</SectionLabel>
                      <FlaskConical aria-hidden="true" className="size-5 text-primary" />
                    </div>
                  </CardHeader>
                  <CardContent>
                    {context.catalyst ? (
                      <>
                        <Badge>{context.catalyst.status}</Badge>
                        <p className="mt-3 font-mono text-xs text-muted-foreground">
                          {formatDate(context.catalyst.windowStart)} –{" "}
                          {formatDate(context.catalyst.windowEnd)}
                        </p>
                        <h2 className="mt-5 font-serif text-3xl leading-tight">
                          {context.catalyst.title}
                        </h2>
                        <blockquote className="mt-5 border-l-2 border-primary pl-4 font-serif text-lg leading-relaxed text-muted-foreground">
                          {context.catalyst.passage}
                        </blockquote>
                        <p className="mt-4 text-xs text-muted-foreground">
                          {context.catalyst.locator}
                        </p>
                        <SourceLink
                          href={context.catalyst.sourceUrl}
                          label="Verify at source"
                        />
                      </>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        No source-backed catalyst ingested.
                      </p>
                    )}
                  </CardContent>
                </Card>

                <Card className="border-challenge/30 xl:col-span-5">
                  <CardHeader>
                    <div className="flex items-center justify-between gap-3">
                      <SectionLabel>Source-backed risk</SectionLabel>
                      <TriangleAlert
                        aria-hidden="true"
                        className="size-5 text-challenge"
                      />
                    </div>
                  </CardHeader>
                  <CardContent>
                    {context.risk ? (
                      <>
                        <div className="flex items-center justify-between gap-3">
                          <Badge variant="destructive">
                            {context.risk.severity} severity
                          </Badge>
                          <span className="font-mono text-xs text-muted-foreground">
                            {context.risk.status}
                          </span>
                        </div>
                        <h2 className="mt-5 font-serif text-3xl leading-tight">
                          {context.risk.title}
                        </h2>
                        <blockquote className="mt-5 border-l-2 border-challenge pl-4 font-serif text-lg leading-relaxed text-muted-foreground">
                          {context.risk.passage}
                        </blockquote>
                        <p className="mt-4 text-xs text-muted-foreground">
                          {context.risk.locator}
                        </p>
                        <SourceLink
                          href={context.risk.sourceUrl}
                          label="Verify risk at source"
                        />
                      </>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        No source-backed active risk ingested.
                      </p>
                    )}
                  </CardContent>
                </Card>

                <Card className="xl:col-span-12">
                  <CardHeader className="sm:grid-cols-[1fr_auto] sm:items-start">
                    <div>
                      <SectionLabel>Price and volume</SectionLabel>
                      <CardTitle className="mt-2">
                        Unadjusted completed daily sessions
                      </CardTitle>
                    </div>
                    {marketSeries ? (
                      <Badge variant="outline">
                        {marketSeries.sessionStart} to {marketSeries.sessionEnd}
                      </Badge>
                    ) : null}
                  </CardHeader>
                  <CardContent>
                    {marketSeries ? (
                      <>
                        <MarketPriceChart bars={marketSeries.bars} />
                        <div className="mt-5 flex flex-col gap-2 border-t border-border pt-4 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
                          <span>
                            {marketSeries.bars.length} stored sessions · gaps
                            preserved · no interpolation
                          </span>
                          <SourceLink
                            href={marketSeries.sourceUrl}
                            label="Open Yahoo Finance history"
                          />
                        </div>
                      </>
                    ) : (
                      <div className="py-10">
                        <Badge variant="attention">Series unavailable</Badge>
                        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-muted-foreground">
                          {marketSeriesResult.unavailableReason ??
                            "No stored OHLCV series for this security. Run server-side yfinance ingestion after operator applies market-series migration."}
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </section>

              {trace ? (
                <Card aria-label="SEC evidence chain" className="mt-1" id="evidence">
                  <CardHeader className="sm:grid-cols-[1fr_auto] sm:items-start">
                    <div>
                      <SectionLabel>Claim evidence</SectionLabel>
                      <CardTitle className="mt-2 font-serif text-3xl">
                        Follow assertion to filing.
                      </CardTitle>
                    </div>
                    <Badge variant="verified">
                      <ShieldCheck aria-hidden="true" />
                      {trace.verificationState}
                    </Badge>
                  </CardHeader>
                  <CardContent className="grid gap-3">
                    <Card className="bg-muted/30">
                      <CardHeader>
                        <SectionLabel>01 / Verified claim</SectionLabel>
                        <CardTitle className="font-serif text-2xl leading-snug sm:text-3xl">
                          {trace.claim}
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <DataList
                          items={[
                            { label: "Research run", value: trace.researchRunId },
                            { label: "Run status", value: trace.runStatus },
                          ]}
                        />
                      </CardContent>
                    </Card>
                    <div className="flex items-center gap-3 px-3 text-[10px] tracking-widest text-muted-foreground uppercase">
                      <Separator className="flex-1" />
                      supports
                      <Separator className="flex-1" />
                    </div>
                    <Card className="bg-muted/30">
                      <CardHeader>
                        <SectionLabel>02 / Exact passage</SectionLabel>
                      </CardHeader>
                      <CardContent>
                        <blockquote className="font-serif text-2xl leading-relaxed text-foreground sm:text-3xl">
                          {trace.passage}
                        </blockquote>
                        <p className="mt-5 text-sm text-muted-foreground">
                          {trace.locator}
                        </p>
                        <p className="mt-3 break-all font-mono text-[10px] text-muted-foreground">
                          SHA-256 {trace.passageSha256}
                        </p>
                      </CardContent>
                    </Card>
                    <div className="flex items-center gap-3 px-3 text-[10px] tracking-widest text-muted-foreground uppercase">
                      <Separator className="flex-1" />
                      from
                      <Separator className="flex-1" />
                    </div>
                    <Card className="bg-muted/30">
                      <CardHeader>
                        <SectionLabel>03 / Original source</SectionLabel>
                        <CardTitle className="font-serif text-2xl sm:text-3xl">
                          {trace.filingForm} for period ended {formatDate(trace.periodEnd)}
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <DataList
                          items={[
                            { label: "Filed", value: formatDate(trace.filedAt) },
                            { label: "Accession", value: trace.accessionNumber },
                            { label: "Retrieved", value: formatDate(trace.retrievedAt) },
                          ]}
                        />
                        <SourceLink href={trace.sourceUrl} label="Open filing on SEC.gov" />
                      </CardContent>
                    </Card>
                  </CardContent>
                </Card>
              ) : null}

            </>
          )}
        </div>
      </main>
    </div>
  );
}
