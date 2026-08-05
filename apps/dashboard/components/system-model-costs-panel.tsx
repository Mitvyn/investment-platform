import {
  CircleDollarSign,
  Cpu,
  Gauge,
  RefreshCcw,
  ShieldCheck,
} from "lucide-react";

import type { ModelCostPresentation } from "@/lib/model-cost-workspace";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

function LedgerCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 border-t border-border px-3 py-4 first:border-t-0 sm:border-t-0 sm:border-l sm:first:border-l-0">
      <dt className="text-[10px] font-medium tracking-[0.1em] text-muted-foreground uppercase">
        {label}
      </dt>
      <dd className="mt-2 font-mono text-sm font-medium [overflow-wrap:anywhere]">
        {value}
      </dd>
    </div>
  );
}

export function SystemModelCostsPanel({
  presentation,
}: {
  presentation: ModelCostPresentation;
}) {
  const summary = presentation.summary;
  return (
    <section className="grid gap-5" aria-labelledby="model-costs-heading">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="mb-2 flex items-center gap-2 font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
            <CircleDollarSign aria-hidden="true" className="size-4" />
            System accounting
          </p>
          <h2
            className="font-serif text-3xl font-medium tracking-tight sm:text-4xl"
            id="model-costs-heading"
          >
            System and model costs
          </h2>
        </div>
        <Badge variant={presentation.status.variant}>
          {presentation.status.label}
        </Badge>
      </div>

      {presentation.kind === "empty" || summary === null ? (
        <Card className="border-warning/35 bg-warning-muted/10">
          <CardHeader>
            <CardTitle>No model accounting has been persisted</CardTitle>
            <CardDescription>{presentation.description}</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="grid gap-5">
          <p className="max-w-4xl text-sm leading-6 text-muted-foreground">
            {presentation.description}
          </p>

          {presentation.blockingReasons.length > 0 ? (
            <Card className="border-warning/35 bg-warning-muted/10">
              <CardHeader>
                <CardTitle>Accounting blockers</CardTitle>
                <CardDescription>
                  These conditions prevent a complete accounting state.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="grid gap-2 text-sm text-muted-foreground">
                  {presentation.blockingReasons.map((reason) => (
                    <li key={reason}>• {reason}</li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Card>
              <CardHeader>
                <Cpu aria-hidden="true" className="size-5 text-primary" />
                <CardTitle>Execution footprint</CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-3 gap-3 text-center">
                <div>
                  <p className="font-mono text-xl">{summary.roleCount}</p>
                  <p className="text-xs text-muted-foreground">Roles</p>
                </div>
                <div>
                  <p className="font-mono text-xl">{summary.attemptCount}</p>
                  <p className="text-xs text-muted-foreground">Attempts</p>
                </div>
                <div>
                  <p className="font-mono text-xl">{summary.reservationCount}</p>
                  <p className="text-xs text-muted-foreground">Reservations</p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <ShieldCheck aria-hidden="true" className="size-5 text-primary" />
                <CardTitle>Validation</CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-3 gap-3 text-center">
                <div>
                  <p className="font-mono text-xl">{summary.validation.passed}</p>
                  <p className="text-xs text-muted-foreground">Passed</p>
                </div>
                <div>
                  <p className="font-mono text-xl">{summary.validation.failed}</p>
                  <p className="text-xs text-muted-foreground">Failed</p>
                </div>
                <div>
                  <p className="font-mono text-xl">{summary.validation.notRun}</p>
                  <p className="text-xs text-muted-foreground">Not run</p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <Gauge aria-hidden="true" className="size-5 text-primary" />
                <CardTitle>Contract signals</CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-3 text-center">
                <div>
                  <p className="font-mono text-xl">
                    {summary.validation.errorCount}
                  </p>
                  <p className="text-xs text-muted-foreground">Validation errors</p>
                </div>
                <div>
                  <p className="font-mono text-xl">
                    {summary.validation.retryCount}
                  </p>
                  <p className="text-xs text-muted-foreground">Retry flags</p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <RefreshCcw aria-hidden="true" className="size-5 text-primary" />
                <CardTitle>Accounting basis</CardTitle>
                <CardDescription>
                  Failed and retried attempts remain included.
                </CardDescription>
              </CardHeader>
            </Card>
          </div>

          <Card aria-label="Model token category ledger">
            <CardHeader>
              <CardTitle>Token ledger</CardTitle>
              <CardDescription>
                Cache writes remain distinct from ordinary uncached input.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="grid overflow-hidden rounded-lg border border-border sm:grid-cols-2 xl:grid-cols-7">
                <LedgerCell label="Input" value={summary.tokens.input} />
                <LedgerCell label="Cached input" value={summary.tokens.cachedInput} />
                <LedgerCell label="Cache write" value={summary.tokens.cacheWrite} />
                <LedgerCell label="Uncached input" value={summary.tokens.uncachedInput} />
                <LedgerCell label="Output" value={summary.tokens.output} />
                <LedgerCell label="Reasoning" value={summary.tokens.reasoning} />
                <LedgerCell label="Total" value={summary.tokens.total} />
              </dl>
            </CardContent>
          </Card>

          <Card aria-label="Model cost ledger">
            <CardHeader>
              <CardTitle>Cost ledger</CardTitle>
              <CardDescription>
                Reservation, deterministic estimate, and provider billing stay separate.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="grid overflow-hidden rounded-lg border border-border sm:grid-cols-2 xl:grid-cols-4">
                <LedgerCell label="Reserved" value={summary.costs.reserved} />
                <LedgerCell label="Reconciled" value={summary.costs.reconciled} />
                <LedgerCell label="Estimated" value={summary.costs.estimated} />
                <LedgerCell label="Provider billed" value={summary.costs.billed} />
              </dl>
            </CardContent>
          </Card>

          <div className="grid gap-4 xl:grid-cols-2" aria-label="Run budgets">
            {presentation.budgets.map((budget) => (
              <Card key={budget.id}>
                <CardHeader className="gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
                  <div>
                    <CardTitle>Run budget</CardTitle>
                    <CardDescription className="mt-2 font-mono text-[11px] [overflow-wrap:anywhere]">
                      {budget.policy}
                    </CardDescription>
                  </div>
                  <Badge variant="outline">{budget.state}</Badge>
                </CardHeader>
                <CardContent>
                  <dl className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2">
                    <LedgerCell label="Hard cost limit" value={budget.hardLimit} />
                    <LedgerCell label="Remaining cost" value={budget.remainingCost} />
                    <LedgerCell label="Reserved" value={budget.reservedCost} />
                    <LedgerCell label="Reconciled" value={budget.reconciledCost} />
                    <LedgerCell label="Hard token limit" value={budget.hardTokens} />
                    <LedgerCell label="Remaining tokens" value={budget.remainingTokens} />
                  </dl>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="grid gap-4" aria-label="Reservation ledger">
            <div>
              <h3 className="font-serif text-2xl font-medium">Reservation ledger</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Reserved, reconciled, and released states remain explicit.
              </p>
            </div>
            {presentation.reservations.map((reservation) => (
              <Card key={reservation.id}>
                <CardHeader className="gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
                  <div>
                    <CardTitle className="capitalize">
                      {reservation.kind} reservation
                    </CardTitle>
                    <CardDescription className="mt-2 font-mono text-[11px] [overflow-wrap:anywhere]">
                      Attempt {reservation.attemptNumber} · {reservation.executionId} · {reservation.id}
                    </CardDescription>
                  </div>
                  <Badge variant="outline">{reservation.state}</Badge>
                </CardHeader>
                <CardContent>
                  <dl className="grid overflow-hidden rounded-lg border border-border sm:grid-cols-2 xl:grid-cols-4">
                    <LedgerCell label="Reserved" value={reservation.reservedCost} />
                    <LedgerCell
                      label="Reconciled"
                      value={reservation.reconciledCost}
                    />
                    <LedgerCell
                      label="Reserved tokens"
                      value={reservation.reservedTokens}
                    />
                    <LedgerCell
                      label="Reconciled tokens"
                      value={reservation.reconciledTokens}
                    />
                    <LedgerCell
                      label="Budget policy"
                      value={reservation.budgetPolicy}
                    />
                    <LedgerCell label="Price card" value={reservation.priceCard} />
                    <LedgerCell label="Reserved at" value={reservation.reservedAt} />
                    <LedgerCell
                      label="Reconciled at"
                      value={reservation.reconciledAt}
                    />
                  </dl>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="grid gap-4" aria-label="Model attempt accounting">
            {presentation.attempts.map((attempt) => (
              <Card key={attempt.id}>
                <CardHeader className="gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
                  <div>
                    <p className="font-mono text-[11px] tracking-[0.08em] text-primary uppercase">
                      {attempt.kind} · attempt {attempt.number}
                    </p>
                    <CardTitle className="mt-2 capitalize">{attempt.role}</CardTitle>
                    <CardDescription className="mt-2">
                      {attempt.provider} · {attempt.model} · {attempt.result}
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {attempt.retryRecorded ? <Badge variant="attention">Retry</Badge> : null}
                    <Badge variant={attempt.status.variant}>{attempt.status.label}</Badge>
                  </div>
                </CardHeader>
                <CardContent className="grid gap-4">
                  <div className="grid gap-4 lg:grid-cols-3">
                    <div className="rounded-lg border border-border p-4">
                      <p className="text-xs font-medium text-muted-foreground">Usage</p>
                      <p className="mt-3 font-mono text-sm">{attempt.tokens.total} tokens</p>
                      <p className="mt-2 text-xs text-muted-foreground">
                        Input {attempt.tokens.input} · output {attempt.tokens.output} · reasoning {attempt.tokens.reasoning}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border p-4">
                      <p className="text-xs font-medium text-muted-foreground">Validation</p>
                      <p className="mt-3 font-mono text-sm">{attempt.validation.status}</p>
                      <p className="mt-2 text-xs text-muted-foreground">
                        Schema {attempt.validation.schema} · citations {attempt.validation.citations} · {attempt.validation.errorCount} errors
                      </p>
                    </div>
                    <div className="rounded-lg border border-border p-4">
                      <p className="text-xs font-medium text-muted-foreground">Cost</p>
                      <p className="mt-3 font-mono text-sm">{attempt.costs.reconciled} reconciled</p>
                      <p className="mt-2 text-xs text-muted-foreground">
                        {attempt.priceCardState} price card · {attempt.costs.estimated} estimated
                      </p>
                    </div>
                  </div>
                  <dl className="grid overflow-hidden rounded-lg border border-border sm:grid-cols-2 xl:grid-cols-7">
                    <LedgerCell label="Input" value={attempt.tokens.input} />
                    <LedgerCell
                      label="Cached input"
                      value={attempt.tokens.cachedInput}
                    />
                    <LedgerCell
                      label="Cache write"
                      value={attempt.tokens.cacheWrite}
                    />
                    <LedgerCell
                      label="Uncached input"
                      value={attempt.tokens.uncachedInput}
                    />
                    <LedgerCell label="Output" value={attempt.tokens.output} />
                    <LedgerCell
                      label="Reasoning"
                      value={attempt.tokens.reasoning}
                    />
                    <LedgerCell label="Total" value={attempt.tokens.total} />
                  </dl>
                  <dl className="grid overflow-hidden rounded-lg border border-border sm:grid-cols-2 xl:grid-cols-4">
                    <LedgerCell label="Model config" value={attempt.modelConfig} />
                    <LedgerCell label="Prompt version" value={attempt.prompt} />
                    <LedgerCell label="Price card" value={attempt.priceCard} />
                    <LedgerCell label="Started" value={attempt.started} />
                    <LedgerCell label="Finished" value={attempt.finished} />
                    <LedgerCell label="Duration" value={attempt.duration} />
                    <LedgerCell label="Reserved" value={attempt.costs.reserved} />
                    <LedgerCell label="Provider billed" value={attempt.costs.billed} />
                  </dl>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
