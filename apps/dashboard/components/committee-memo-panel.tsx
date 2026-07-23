import {
  AlertTriangle,
  BookOpenCheck,
  CalendarClock,
  FileSearch,
  GitCompareArrows,
  ShieldCheck,
} from "lucide-react";

import type { presentCommitteeMemoWorkspace } from "@/lib/committee-memo-workspace";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type Presentation = ReturnType<typeof presentCommitteeMemoWorkspace>;
type ReadyPresentation = Extract<Presentation, { kind: "ready" }>;
type Statement = ReadyPresentation["commonGround"][number];

function ReferenceGroup({ ids, label }: { ids: string[]; label: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-mono text-[11px] leading-5 [overflow-wrap:anywhere]">
        {ids.length > 0 ? ids.join(", ") : "None"}
      </dd>
    </div>
  );
}

function StatementCard({ statement }: { statement: Statement }) {
  const variant =
    statement.provenanceCode === "fact"
      ? "verified"
      : statement.provenanceCode === "gap"
        ? "attention"
        : statement.provenanceCode === "assumption"
          ? "secondary"
          : "outline";

  return (
    <div className="grid gap-4 rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-4xl text-sm leading-6">{statement.text}</p>
        <Badge variant={variant}>{statement.provenanceType}</Badge>
      </div>
      <p className="font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
        {statement.id}
      </p>
      <dl className="grid gap-3 border-t border-border pt-3 md:grid-cols-3">
        <ReferenceGroup ids={statement.evidenceIds} label="Evidence IDs" />
        <ReferenceGroup ids={statement.opinionIds} label="Opinion IDs" />
        <ReferenceGroup ids={statement.calculationIds} label="Calculation IDs" />
      </dl>
    </div>
  );
}

function StatementSection({
  empty,
  statements,
  title,
}: {
  empty: string;
  statements: Statement[];
  title: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        {statements.length === 0 ? (
          <p className="text-sm text-muted-foreground">{empty}</p>
        ) : (
          statements.map((statement) => (
            <StatementCard key={statement.id} statement={statement} />
          ))
        )}
      </CardContent>
    </Card>
  );
}

export function CommitteeMemoPanel({
  presentation,
}: {
  presentation: Presentation;
}) {
  if (presentation.kind === "missing") {
    return (
      <section className="grid gap-5" aria-labelledby="committee-memo-heading">
        <div>
          <p className="mb-2 font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
            Committee synthesis
          </p>
          <h2
            className="font-serif text-3xl font-medium tracking-tight sm:text-4xl"
            id="committee-memo-heading"
          >
            Provenance-safe memo
          </h2>
        </div>
        <Card className="border-warning/35 bg-warning-muted/10">
          <CardHeader>
            <CardTitle>{presentation.title}</CardTitle>
            <CardDescription>{presentation.description}</CardDescription>
          </CardHeader>
        </Card>
      </section>
    );
  }

  return (
    <section className="grid gap-5" aria-labelledby="committee-memo-heading">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="mb-2 flex items-center gap-2 font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
            <BookOpenCheck aria-hidden="true" className="size-4" />
            Committee synthesis
          </p>
          <h2
            className="font-serif text-3xl font-medium tracking-tight sm:text-4xl"
            id="committee-memo-heading"
          >
            Provenance-safe memo
          </h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="verified">{presentation.validationState}</Badge>
          <Badge variant="outline">
            Requested disposition: {presentation.requestedDisposition}
          </Badge>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
        <Card aria-label="Committee memo identity">
          <CardHeader>
            <FileSearch aria-hidden="true" className="size-5 text-primary" />
            <CardTitle>Immutable synthesis identity</CardTitle>
            <CardDescription>
              Exact committee and frozen bundle used by reconciliation.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-3 text-xs sm:grid-cols-2">
              {[
                ["Memo ID", presentation.identity.memoId],
                ["Synthesis execution", presentation.identity.synthesisExecutionId],
                ["Committee ID", presentation.identity.committeeId],
                ["Bundle ID", presentation.identity.evidenceBundleId],
                ["Bundle hash", presentation.identity.evidenceBundleHash],
                ["Contract", presentation.identity.contractVersion],
              ].map(([label, value]) => (
                <div className="min-w-0 rounded-lg border border-border p-3" key={label}>
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="mt-1 font-mono [overflow-wrap:anywhere]">{value}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>

        <Card aria-label="Committee memo validation and retry">
          <CardHeader>
            <ShieldCheck aria-hidden="true" className="size-5 text-primary" />
            <CardTitle>Validation and retry</CardTitle>
            <CardDescription>
              Accepted canonical output only. Raw provider bodies remain audit-restricted.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm">
            <p><span className="text-muted-foreground">Validation:</span> {presentation.validationState}</p>
            <p><span className="text-muted-foreground">Retry:</span> {presentation.retryState}</p>
            <p><span className="text-muted-foreground">Attempts:</span> {presentation.execution.attemptCount}</p>
            <p className="font-mono text-xs [overflow-wrap:anywhere]">
              {presentation.execution.configuration.modelConfigId} · {presentation.execution.configuration.promptVersion}
            </p>
            <p className="font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">
              {presentation.execution.configuration.provider} / {presentation.execution.configuration.model}
            </p>
            <p><span className="text-muted-foreground">Price card:</span> {presentation.execution.configuration.priceCard}</p>
            <p><span className="text-muted-foreground">Retry policy:</span> {presentation.execution.configuration.retryPolicy}</p>
            <p><span className="text-muted-foreground">Estimated cost:</span> {presentation.execution.estimatedCost}</p>
            <p><span className="text-muted-foreground">Usage completeness:</span> {presentation.execution.usage.completeness}</p>
          </CardContent>
        </Card>
      </div>

      <Card aria-label="Synthesis attempt chronology">
        <CardHeader>
          <ShieldCheck aria-hidden="true" className="size-5 text-primary" />
          <CardTitle>Synthesis attempt chronology</CardTitle>
          <CardDescription>
            Prompt/config binding, validation, token usage, and cost. Provider bodies and reasoning content remain restricted.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {presentation.execution.attempts.map((attempt) => (
            <div className="grid gap-4 rounded-lg border border-border p-4" key={attempt.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-medium">Attempt {attempt.number}</p>
                  <p className="mt-1 font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                    {attempt.id} · {attempt.providerRequestId}
                  </p>
                </div>
                <Badge variant={attempt.status.variant}>{attempt.status.label}</Badge>
              </div>
              <dl className="grid gap-3 text-xs sm:grid-cols-2 xl:grid-cols-4">
                {[
                  ["Started", attempt.startedAt],
                  ["Completed", attempt.completedAt],
                  ["Duration", attempt.duration],
                  ["Validation", attempt.validation.label],
                  ["Input", attempt.usage.inputTokens],
                  ["Cached input", attempt.usage.cachedInputTokens],
                  ["Cache write", attempt.usage.cacheWriteTokens],
                  ["Uncached input", attempt.usage.uncachedInputTokens],
                  ["Output", attempt.usage.outputTokens],
                  ["Reasoning", attempt.usage.reasoningTokens],
                  ["Total", attempt.usage.totalTokens],
                  ["Usage completeness", attempt.usage.completeness],
                  ["Estimated cost", attempt.estimatedCost],
                  ["Retry reason", attempt.retryReason ?? "None"],
                  ["Validation errors", attempt.validation.errors.join(", ") || "None"],
                ].map(([label, value]) => (
                  <div className="min-w-0 rounded-lg border border-border p-3" key={label}>
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="mt-1 font-mono [overflow-wrap:anywhere]">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </CardContent>
      </Card>

      <StatementSection
        empty="No executive summary statements recorded."
        statements={presentation.executiveSummary}
        title="Executive summary"
      />
      <StatementSection
        empty="No common ground recorded."
        statements={presentation.commonGround}
        title="Common ground"
      />

      <Card aria-label="Material disagreements">
        <CardHeader>
          <GitCompareArrows aria-hidden="true" className="size-5 text-primary" />
          <CardTitle>Material disagreements</CardTitle>
          <CardDescription>
            Positions stay attached to contributing opinions. Counts do not resolve them.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {presentation.disagreements.length === 0 ? (
            <p className="text-sm text-muted-foreground">No material disagreement recorded.</p>
          ) : (
            presentation.disagreements.map((disagreement) => (
              <div className="grid gap-4 rounded-lg border border-warning/35 bg-warning-muted/10 p-4" key={disagreement.id}>
                <div className="flex flex-wrap justify-between gap-2">
                  <p className="font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">{disagreement.id}</p>
                  <Badge variant={disagreement.affectsDisposition ? "attention" : "outline"}>
                    {disagreement.affectsDisposition ? "Affects disposition" : "Does not affect disposition"}
                  </Badge>
                </div>
                <StatementCard statement={disagreement.disputedQuestion} />
                <div className="grid gap-3 lg:grid-cols-2">
                  {disagreement.positions.map((statement) => (
                    <StatementCard key={statement.id} statement={statement} />
                  ))}
                </div>
                <div>
                  <p className="mb-2 text-xs font-medium">Contributing Opinion IDs</p>
                  <p className="font-mono text-[11px] [overflow-wrap:anywhere]">
                    {disagreement.contributingOpinionIds.join(", ")}
                  </p>
                </div>
                {disagreement.resolvingEvidence.map((statement) => (
                  <StatementCard key={statement.id} statement={statement} />
                ))}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <StatementSection empty="No disputed assumptions recorded." statements={presentation.disputedAssumptions} title="Disputed assumptions" />
        <StatementSection empty="No evidence gaps recorded." statements={presentation.evidenceGaps} title="Evidence gaps" />
        <StatementSection empty="No invalidation conditions recorded." statements={presentation.invalidations} title="Invalidation conditions" />
        <StatementSection empty="No next evidence recorded." statements={presentation.requiredNextEvidence} title="Required next evidence" />
      </div>

      <Card aria-label="Review trigger">
        <CardHeader>
          <CalendarClock aria-hidden="true" className="size-5 text-primary" />
          <CardTitle>Review trigger</CardTitle>
          <CardDescription>
            {presentation.reviewTrigger.type}
            {presentation.reviewTrigger.reviewAt ? ` · ${presentation.reviewTrigger.reviewAt}` : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <StatementCard statement={presentation.reviewTrigger.statement} />
        </CardContent>
      </Card>

      <Card aria-label="Execution-state disclosure">
        <CardHeader>
          <AlertTriangle aria-hidden="true" className="size-5 text-primary" />
          <CardTitle>Execution-state disclosure</CardTitle>
          <CardDescription>
            Exact grader states and accepted stances used during synthesis.
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[42rem] border-collapse text-left text-sm">
            <thead className="border-b border-border text-xs text-muted-foreground">
              <tr><th className="py-3 pr-4">Grader</th><th className="px-4 py-3">State</th><th className="px-4 py-3">Stance</th><th className="py-3 pl-4">Opinion ID</th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {presentation.states.map((state) => (
                <tr key={state.graderId}>
                  <th className="py-3 pr-4 font-medium">{state.graderLabel}</th>
                  <td className="px-4 py-3">{state.executionState}</td>
                  <td className="px-4 py-3">{state.stance}</td>
                  <td className="py-3 pl-4 font-mono text-xs [overflow-wrap:anywhere]">{state.opinionId ?? "None"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </section>
  );
}
