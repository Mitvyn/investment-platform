import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  importQuantDatasetAction,
  runQuantAnalysisAction,
} from "@/app/quant-actions";
import type { QuantWorkspaceView } from "@/lib/quant-workspace";

/**
 * The Quant workspace.
 *
 * Architecture decision 0001 keeps Quant in its own bounded context: it shares
 * the canonical `security_id` with the other features and nothing else. No
 * research state and no account data reaches this surface, and nothing
 * produced here is evidence, a signal, or an instruction to trade.
 *
 * What it offers is one honest loop: import a dated local price dataset, state
 * every assumption, run a fixed rule against sessions that already happened,
 * and read what that would have done next to buying once and keeping it, with
 * the limits of the exercise stated beside the numbers rather than buried.
 */

/** Starting values for the assumption form. Every one is editable and stated. */
export const QUANT_ASSUMPTION_DEFAULTS: Record<string, string> = {
  alpha: "0.05",
  annualisation_periods: "252",
  commission_bps: "0",
  commission_minimum: "1.00",
  commission_per_share: "0.005",
  cost_stress_multiplier: "3",
  embargo_sessions: "1",
  lookback_sessions: "20",
  max_participation_bps: "500",
  min_fill_shares: "1",
  min_total_trades: "1",
  min_trades_per_window: "0",
  min_windows: "3",
  slippage_bps: "5",
  starting_cash: "100000.00",
  step_sessions: "20",
  test_sessions: "20",
  train_sessions: "60",
  transaction_cost_bps: "2",
  trials_declared: "2",
};

const ASSUMPTION_FIELDS: Array<{
  help: string;
  label: string;
  name: string;
}> = [
  {
    help: "Cash the analysis starts with. Every result below is measured against it.",
    label: "Starting cash",
    name: "starting_cash",
  },
  {
    help: "Broker charge per share traded.",
    label: "Commission per share",
    name: "commission_per_share",
  },
  {
    help: "Broker charge as hundredths of a percent of the traded value.",
    label: "Commission (bps)",
    name: "commission_bps",
  },
  {
    help: "Smallest commission charged on any single trade.",
    label: "Minimum commission",
    name: "commission_minimum",
  },
  {
    help: "Exchange, clearing, and regulatory charges on traded value, in hundredths of a percent.",
    label: "Transaction cost (bps)",
    name: "transaction_cost_bps",
  },
  {
    help: "How far the fill price moves against you, in hundredths of a percent.",
    label: "Slippage (bps)",
    name: "slippage_bps",
  },
  {
    help: "The largest share of a session's traded volume this analysis may take. 500 means five percent.",
    label: "Participation limit (bps)",
    name: "max_participation_bps",
  },
  {
    help: "Fills smaller than this are dropped instead of executed.",
    label: "Minimum fill (shares)",
    name: "min_fill_shares",
  },
  {
    help: "How many sessions the trailing average covers. The rule is invested while the latest close sits above that average.",
    label: "Trend lookback (sessions)",
    name: "lookback_sessions",
  },
  {
    help: "Sessions in each training window. No parameter is fitted from them today, and the rule never sees past them.",
    label: "Training sessions",
    name: "train_sessions",
  },
  {
    help: "Sessions in each out-of-sample test window.",
    label: "Test sessions",
    name: "test_sessions",
  },
  {
    help: "How far each window moves forward. A step smaller than the test length makes windows overlap.",
    label: "Step (sessions)",
    name: "step_sessions",
  },
  {
    help: "Sessions dropped between training and testing so the two do not touch.",
    label: "Embargo (sessions)",
    name: "embargo_sessions",
  },
  {
    help: "Fewer windows than this and no verdict is attempted at all.",
    label: "Minimum windows",
    name: "min_windows",
  },
  {
    help: "Windows with fewer trades than this count as an inadequate sample.",
    label: "Minimum trades per window",
    name: "min_trades_per_window",
  },
  {
    help: "Total trades below this and the whole run counts as an inadequate sample.",
    label: "Minimum total trades",
    name: "min_total_trades",
  },
  {
    help: "Trading sessions per year, used to put daily figures on an annual footing. 252 is the usual count.",
    label: "Sessions per year",
    name: "annualisation_periods",
  },
  {
    help: "How unlikely a result must be before it counts as more than chance. Smaller is stricter.",
    label: "Significance level",
    name: "alpha",
  },
  {
    help: "How much costs are multiplied by in the stress scenario, to see whether the result depends on them.",
    label: "Cost stress multiplier",
    name: "cost_stress_multiplier",
  },
  {
    help: "How many configurations you have tried in total. Declaring more makes the threshold stricter. Nothing here can check this number.",
    label: "Configurations tried",
    name: "trials_declared",
  },
];

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-[11px] font-medium tracking-[0.14em] text-primary uppercase">
      {children}
    </p>
  );
}

export function QuantPanel({
  defaults = QUANT_ASSUMPTION_DEFAULTS,
  securityId,
  ticker,
  view,
}: {
  defaults?: Record<string, string>;
  securityId: string | null;
  ticker: string;
  view: QuantWorkspaceView;
}) {
  const identity = securityId ?? "";
  const canImport = view.state !== "unavailable" && identity.length > 0;

  return (
    <Card className="mt-5">
      <CardHeader>
        <SectionTitle>Quant historical analysis</SectionTitle>
        <CardTitle className="mt-2">
          {ticker ? `${ticker} historical analysis` : "Historical analysis"}
        </CardTitle>
        <p className="mt-2 text-sm text-muted-foreground">{view.headline}</p>
      </CardHeader>
      <CardContent>
        {view.errorMessage ? (
          <p
            className="mb-5 rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm"
            role="alert"
          >
            {view.errorMessage}
          </p>
        ) : null}

        <section className="rounded-lg border border-border px-4 py-4">
          <SectionTitle>Dataset</SectionTitle>
          {view.datasetSummary ? (
            <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-xs text-muted-foreground">Known as of</dt>
                <dd className="font-mono">{view.datasetSummary.cutoff}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Sessions</dt>
                <dd className="font-mono">
                  {view.datasetSummary.sessionCount} (
                  {view.datasetSummary.firstSession} to{" "}
                  {view.datasetSummary.lastSession})
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Source revision</dt>
                <dd className="font-mono">{view.datasetSummary.sourceRevision}</dd>
              </div>
            </dl>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">
              No dataset is active for this security. Import a daily open, high,
              low, close, and volume file that states its own as-of cutoff,
              source revision, and content hash. Nothing is downloaded for you.
            </p>
          )}
          <form action={importQuantDatasetAction} className="mt-4 flex gap-3">
            <input name="securityId" type="hidden" value={identity} />
            <input
              className="flex-1 rounded-md border border-border bg-transparent px-3 py-2 font-mono text-xs"
              name="datasetPath"
              placeholder="/absolute/path/to/dataset.json"
              required
              type="text"
            />
            <Button disabled={!canImport} type="submit" variant="outline">
              Import dataset
            </Button>
          </form>
        </section>

        <form action={runQuantAnalysisAction} className="mt-5">
          <input name="securityId" type="hidden" value={identity} />
          <section className="rounded-lg border border-border px-4 py-4">
            <SectionTitle>Assumptions</SectionTitle>
            <p className="mt-2 text-xs text-muted-foreground">
              Every value is stated, none is assumed for you, and all of them are
              recorded with the result.
            </p>
            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {ASSUMPTION_FIELDS.map((field) => (
                <label className="block text-sm" key={field.name}>
                  <span className="font-medium">{field.label}</span>
                  <input
                    className="mt-1 w-full rounded-md border border-border bg-transparent px-3 py-2 font-mono text-xs"
                    defaultValue={defaults[field.name] ?? ""}
                    name={field.name}
                    required
                    type="text"
                  />
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {field.help}
                  </span>
                </label>
              ))}
            </div>
            <Button className="mt-4" disabled={!view.canRun} type="submit">
              Run analysis
            </Button>
          </section>
        </form>

        {view.state === "result_ready" ? (
          <>
            <section className="mt-5 grid gap-3 sm:grid-cols-2">
              {view.metrics.map((metric) => (
                <div
                  className="rounded-lg border border-border px-4 py-3"
                  key={metric.label}
                >
                  <p className="text-xs text-muted-foreground">{metric.label}</p>
                  <p className="mt-1 font-mono text-lg">{metric.value}</p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {metric.plainLanguage}
                  </p>
                </div>
              ))}
            </section>

            {view.benchmark ? (
              <section className="mt-5 rounded-lg border border-border px-4 py-4">
                <SectionTitle>Benchmark</SectionTitle>
                <div className="mt-3 flex flex-wrap items-baseline gap-4 font-mono text-sm">
                  <span>Rule {view.benchmark.strategyReturn}</span>
                  <span>
                    {view.benchmark.label} {view.benchmark.benchmarkReturn}
                  </span>
                  <Badge
                    variant={view.benchmark.strategyAhead ? "default" : "secondary"}
                  >
                    {view.benchmark.strategyAhead ? "Rule ahead" : "Benchmark ahead"}
                  </Badge>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  {view.benchmark.plainLanguage}
                </p>
              </section>
            ) : null}

            {view.validation ? (
              <section className="mt-5 rounded-lg border border-border px-4 py-4">
                <SectionTitle>Walk-forward validation</SectionTitle>
                <p className="mt-2 text-sm font-medium">
                  {view.validation.headline}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {view.validation.plainLanguage}
                </p>
                <p className="mt-3 font-mono text-xs">
                  {view.validation.windowsBeatingBenchmark} of{" "}
                  {view.validation.windowCount} windows ahead of the benchmark
                </p>
                {view.validation.gaps.length > 0 ? (
                  <ul className="mt-3 grid gap-2">
                    {view.validation.gaps.map((gap) => (
                      <li
                        className="rounded-md border border-dashed border-border px-3 py-2 text-xs"
                        key={gap.label}
                      >
                        <span className="font-medium">{gap.label}. </span>
                        {gap.explanation}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </section>
            ) : null}

            <section className="mt-5 rounded-lg border border-border px-4 py-4">
              <SectionTitle>What this cannot tell you</SectionTitle>
              <ul className="mt-3 grid gap-2 text-xs text-muted-foreground">
                {view.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            </section>
          </>
        ) : null}

        {view.detail.length > 0 ? (
          <details className="mt-5 rounded-lg border border-border px-4 py-3">
            <summary className="cursor-pointer text-sm font-medium">
              Provenance and configuration
            </summary>
            <dl className="mt-3 grid gap-2 text-xs">
              {view.detail.map((entry) => (
                <div className="flex flex-wrap gap-2" key={entry.label}>
                  <dt className="text-muted-foreground">{entry.label}</dt>
                  <dd className="font-mono break-all">{entry.value}</dd>
                </div>
              ))}
            </dl>
          </details>
        ) : null}

        <p className="mt-5 text-xs text-muted-foreground">{view.disclaimer}</p>
      </CardContent>
    </Card>
  );
}
