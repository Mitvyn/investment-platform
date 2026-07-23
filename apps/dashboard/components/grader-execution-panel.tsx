import {
  BrainCircuit,
  Check,
  CircleDollarSign,
  FileCheck2,
  Fingerprint,
  LockKeyhole,
  ShieldCheck,
  X,
} from "lucide-react";

import type { presentGraderExecutionWorkspace } from "@/lib/grader-execution-workspace";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

type Presentation = ReturnType<typeof presentGraderExecutionWorkspace>;

function FieldList({
  fields,
}: {
  fields: Array<{ label: string; value: string }>;
}) {
  return (
    <dl className="grid gap-0">
      {fields.map((field, index) => (
        <div key={field.label}>
          {index > 0 ? <Separator /> : null}
          <div className="grid min-w-0 gap-1 py-3 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-5">
            <dt className="text-xs font-medium text-muted-foreground">
              {field.label}
            </dt>
            <dd className="min-w-0 font-mono text-xs leading-5 [overflow-wrap:anywhere] sm:text-right">
              {field.value}
            </dd>
          </div>
        </div>
      ))}
    </dl>
  );
}

function EvidenceList({
  empty,
  items,
}: {
  empty: string;
  items: string[];
}) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{empty}</p>;
  }
  return (
    <ul className="grid list-disc gap-2 pl-5 text-sm leading-6">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export function GraderExecutionPanel({
  presentation,
}: {
  presentation: Presentation;
}) {
  return (
    <section className="grid gap-5" aria-labelledby="grader-executions-heading">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="mb-2 flex items-center gap-2 font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
            <BrainCircuit aria-hidden="true" className="size-4" />
            Isolated grader
          </p>
          <h2
            className="font-serif text-3xl font-medium tracking-tight sm:text-4xl"
            id="grader-executions-heading"
          >
            Execution and opinion audit
          </h2>
        </div>
        <Badge variant={presentation.status.variant}>
          {presentation.status.label}
        </Badge>
      </div>

      {presentation.kind === "missing" ? (
        <Card className="border-warning/35 bg-warning-muted/10">
          <CardHeader>
            <CardTitle>Grader execution unavailable</CardTitle>
            <CardDescription>{presentation.description}</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="grid gap-6">
          {presentation.executions.map((execution) => (
            <article className="grid gap-4" key={execution.identity.id}>
              <Card>
                <CardHeader className="gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
                  <div className="min-w-0">
                    <p className="font-mono text-[11px] tracking-[0.08em] text-primary uppercase">
                      {execution.identity.grader} grader
                    </p>
                    <CardTitle className="mt-2 capitalize">
                      {execution.identity.grader.replaceAll("_", " ")}
                    </CardTitle>
                    <CardDescription className="mt-3">
                      Separate execution against one frozen Evidence Bundle. No
                      other grader opinion enters this context.
                    </CardDescription>
                  </div>
                  <Badge variant={execution.status.variant}>
                    {execution.status.label}
                  </Badge>
                </CardHeader>
              </Card>

              {execution.outcome?.kind === "not_executed" ? (
                <Card className="border-warning/35 bg-warning-muted/10">
                  <CardHeader>
                    <CardTitle>Provider was not called</CardTitle>
                    <CardDescription>{execution.outcome.reason}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <FieldList
                      fields={[
                        { label: "Reason code", value: execution.outcome.reasonCode },
                        { label: "Gate policy", value: execution.outcome.policy },
                        {
                          label: "Failed checks",
                          value: execution.outcome.failedChecks.join(", "),
                        },
                      ]}
                    />
                  </CardContent>
                </Card>
              ) : null}

              {execution.outcome?.kind === "failed" ? (
                <Card className="border-challenge/35 bg-challenge-muted/10">
                  <CardHeader>
                    <CardTitle>Required grader unavailable</CardTitle>
                    <CardDescription>{execution.outcome.finalReason}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <FieldList
                      fields={[
                        { label: "Category", value: execution.outcome.category },
                        {
                          label: "Attempts",
                          value: String(execution.outcome.attemptCount),
                        },
                        {
                          label: "Validation errors",
                          value:
                            execution.outcome.validationErrors.join(", ") || "None",
                        },
                        { label: "Retry policy", value: execution.outcome.retryPolicy },
                      ]}
                    />
                  </CardContent>
                </Card>
              ) : null}

              <div className="grid gap-4 xl:grid-cols-2">
                <Card aria-label="Grader execution identity">
                  <CardHeader>
                    <div className="mb-2 flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <Fingerprint aria-hidden="true" className="size-4" />
                    </div>
                    <CardTitle>Execution identity</CardTitle>
                    <CardDescription>
                      Immutable key, grader, and frozen bundle binding.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <FieldList
                      fields={[
                        { label: "Execution ID", value: execution.identity.id },
                        { label: "Execution key", value: execution.identity.executionKey },
                        { label: "Grader version", value: execution.identity.graderVersion },
                        { label: "Roster status", value: execution.identity.required },
                        { label: "Bundle ID", value: execution.identity.bundleId },
                        { label: "Bundle hash", value: execution.identity.bundleHash },
                        { label: "Started", value: execution.identity.started },
                        { label: "Finished", value: execution.identity.finished },
                      ]}
                    />
                  </CardContent>
                </Card>

                <Card aria-label="Pinned grader configuration">
                  <CardHeader>
                    <div className="mb-2 flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <LockKeyhole aria-hidden="true" className="size-4" />
                    </div>
                    <CardTitle>Pinned configuration</CardTitle>
                    <CardDescription>
                      Provider, model, prompt, rubric, schema, and retry versions.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <FieldList
                      fields={[
                        { label: "Provider", value: execution.configuration.provider },
                        { label: "Model", value: execution.configuration.model },
                        { label: "Model config", value: execution.configuration.modelConfig },
                        { label: "Prompt", value: execution.configuration.prompt },
                        {
                          label: "Grader contract",
                          value: execution.configuration.graderContract,
                        },
                        { label: "Rubric", value: execution.configuration.rubric },
                        {
                          label: "Output schema",
                          value: execution.configuration.outputSchema,
                        },
                        {
                          label: "Abstention rules",
                          value: execution.configuration.abstentionRules,
                        },
                        {
                          label: "Retry policy",
                          value: execution.configuration.retryPolicy,
                        },
                        {
                          label: "Inference hash",
                          value: execution.configuration.inferenceParameters,
                        },
                      ]}
                    />
                  </CardContent>
                </Card>
              </div>

              <Card aria-label="Pre-call execution gate">
                <CardHeader className="gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
                  <div>
                    <div className="mb-2 flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <ShieldCheck aria-hidden="true" className="size-4" />
                    </div>
                    <CardTitle>Pre-call gate</CardTitle>
                    <CardDescription className="mt-2">
                      {execution.gate.policy} · checked {execution.gate.checked}
                    </CardDescription>
                  </div>
                  <Badge variant={execution.gate.status.variant}>
                    {execution.gate.status.label}
                  </Badge>
                </CardHeader>
                <CardContent>
                  <div className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 xl:grid-cols-4">
                    {execution.gate.checks.map((check) => (
                      <div className="min-w-0 bg-card p-4" key={check.id}>
                        <div className="flex items-start justify-between gap-3">
                          <p className="text-xs font-medium">{check.label}</p>
                          <Badge variant={check.status.variant}>
                            {check.passed ? (
                              <Check aria-hidden="true" />
                            ) : (
                              <X aria-hidden="true" />
                            )}
                            {check.status.label}
                          </Badge>
                        </div>
                        <p className="mt-3 font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                          {check.reason}
                        </p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <div className="grid gap-4 lg:grid-cols-3">
                <Card>
                  <CardHeader>
                    <CircleDollarSign aria-hidden="true" className="size-5 text-primary" />
                    <CardTitle>Budget</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <FieldList
                      fields={[
                        { label: "State", value: execution.budget.status },
                        { label: "Policy", value: execution.budget.policy },
                        { label: "Reserved", value: execution.budget.reserved },
                        { label: "Reconciled", value: execution.budget.reconciled },
                      ]}
                    />
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <BrainCircuit aria-hidden="true" className="size-5 text-primary" />
                    <CardTitle>Token usage</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <FieldList
                      fields={[
                        { label: "Input", value: execution.usage.inputTokens },
                        { label: "Cached input", value: execution.usage.cachedInputTokens },
                        {
                          label: "Uncached input",
                          value: execution.usage.uncachedInputTokens,
                        },
                        { label: "Output", value: execution.usage.outputTokens },
                        { label: "Reasoning", value: execution.usage.reasoningTokens },
                        { label: "Total", value: execution.usage.totalTokens },
                        { label: "Usage", value: execution.usage.completeness },
                      ]}
                    />
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <FileCheck2 aria-hidden="true" className="size-5 text-primary" />
                    <CardTitle>Execution cost</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <FieldList
                      fields={[
                        { label: "Reserved", value: execution.cost.reserved },
                        { label: "Estimated", value: execution.cost.estimated },
                        { label: "Billed", value: execution.cost.billed },
                        { label: "Price card", value: execution.cost.priceCard },
                      ]}
                    />
                  </CardContent>
                </Card>
              </div>

              <div className="grid gap-4" aria-label="Grader attempt chronology">
                {execution.attempts.length === 0 ? (
                  <Card>
                    <CardContent className="p-5 text-sm text-muted-foreground sm:p-6">
                      No provider attempt created.
                    </CardContent>
                  </Card>
                ) : (
                  execution.attempts.map((attempt) => (
                    <Card key={attempt.id}>
                      <CardHeader className="gap-4 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:items-start">
                        <div className="flex size-10 items-center justify-center rounded-lg border border-primary/30 bg-primary/10 font-mono text-sm text-primary">
                          {attempt.number}
                        </div>
                        <div>
                          <CardTitle>Attempt {attempt.number}</CardTitle>
                          <CardDescription className="mt-2">
                            {attempt.provider} · {attempt.model} · {attempt.duration}
                          </CardDescription>
                        </div>
                        <Badge variant={attempt.status.variant}>
                          {attempt.status.label}
                        </Badge>
                      </CardHeader>
                      <CardContent className="grid gap-4 xl:grid-cols-3">
                        <div className="rounded-lg border border-border p-4">
                          <p className="text-xs font-medium text-muted-foreground">
                            Immutable request
                          </p>
                          <p className="mt-3 font-mono text-xs [overflow-wrap:anywhere]">
                            {attempt.requestHash}
                          </p>
                          <p className="mt-3 text-xs text-muted-foreground">
                            {attempt.rawOutputState}
                          </p>
                          {attempt.retryReason !== null ? (
                            <p className="mt-3 font-mono text-xs text-warning-muted-foreground [overflow-wrap:anywhere]">
                              Retry: {attempt.retryReason}
                            </p>
                          ) : null}
                        </div>
                        <div className="rounded-lg border border-border p-4">
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-xs font-medium text-muted-foreground">
                              Validation
                            </p>
                            <Badge variant={attempt.validation.variant}>
                              {attempt.validation.label}
                            </Badge>
                          </div>
                          <p className="mt-3 font-mono text-xs">
                            Schema {attempt.validation.schema} · citations {attempt.validation.citations}
                          </p>
                          <EvidenceList
                            empty="No validation errors."
                            items={attempt.validation.errors}
                          />
                        </div>
                        <div className="rounded-lg border border-border p-4">
                          <p className="text-xs font-medium text-muted-foreground">
                            Usage and cost
                          </p>
                          <p className="mt-3 font-mono text-xs">
                            {attempt.usage.totalTokens} tokens
                          </p>
                          <p className="mt-2 font-mono text-xs">
                            {attempt.cost.estimated} estimated
                          </p>
                          <p className="mt-2 font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                            {attempt.cost.priceCard}
                          </p>
                        </div>
                      </CardContent>
                    </Card>
                  ))
                )}
              </div>

              {execution.opinion !== null ? (
                <Card aria-label="Validated grader opinion">
                  <CardHeader className="gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
                    <div>
                      <CardTitle>Validated opinion</CardTitle>
                      <CardDescription className="mt-2">
                        {execution.opinion.ownedQuestion}
                      </CardDescription>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Badge variant={execution.opinion.stance.variant}>
                        {execution.opinion.stance.label}
                      </Badge>
                      <Badge variant="outline">
                        {execution.opinion.confidence} confidence
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="grid gap-6">
                    <p className="max-w-5xl text-base leading-7">
                      {execution.opinion.summary}
                    </p>

                    {execution.opinion.abstention !== null ? (
                      <div className="rounded-lg border border-warning/35 bg-warning-muted/10 p-5">
                        <p className="font-medium">Abstention</p>
                        <p className="mt-2 text-sm leading-6">
                          {execution.opinion.abstention.reason}
                        </p>
                        <p className="mt-3 font-mono text-xs text-warning-muted-foreground">
                          {execution.opinion.abstention.reasonCode}
                        </p>
                        <div className="mt-4 grid gap-4 md:grid-cols-2">
                          <div>
                            <p className="mb-2 text-xs font-medium text-muted-foreground">
                              Missing or inadequate
                            </p>
                            <EvidenceList
                              empty="None stated."
                              items={execution.opinion.abstention.missingEvidence}
                            />
                          </div>
                          <div>
                            <p className="mb-2 text-xs font-medium text-muted-foreground">
                              Evidence required
                            </p>
                            <EvidenceList
                              empty="None stated."
                              items={execution.opinion.abstention.evidenceRequired}
                            />
                          </div>
                        </div>
                      </div>
                    ) : null}

                    <div className="rounded-lg border border-primary/25 bg-primary/5 p-5">
                      <p className="font-mono text-[11px] tracking-[0.08em] text-primary uppercase">
                        Shared proposition
                      </p>
                      <p className="mt-3 font-serif text-xl leading-snug">
                        {execution.opinion.proposition.text}
                      </p>
                      <p className="mt-3 text-sm leading-6 text-muted-foreground">
                        {execution.opinion.proposition.rationale ??
                          "No stance rationale because grader abstained."}
                      </p>
                    </div>

                    <div className="grid gap-4">
                      {execution.opinion.claims.map((claim) => (
                        <div className="rounded-lg border border-evidence/30 bg-evidence-muted/20 p-5" key={claim.id}>
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="verified">Citation valid</Badge>
                            <Badge variant="outline">{claim.materiality}</Badge>
                          </div>
                          <p className="mt-4 text-sm leading-6">{claim.claim}</p>
                          <p className="mt-3 font-mono text-[11px] text-evidence-muted-foreground [overflow-wrap:anywhere]">
                            {claim.evidenceIds.join(", ")}
                          </p>
                        </div>
                      ))}
                    </div>

                    <div className="grid gap-4 lg:grid-cols-2">
                      <div className="rounded-lg border border-border p-5">
                        <p className="text-sm font-medium">
                          {execution.opinion.domain.title}
                        </p>
                        <FieldList fields={execution.opinion.domain.fields} />
                      </div>
                      <div className="grid gap-4">
                        {execution.opinion.domain.sections.map((section) => (
                          <div
                            className="rounded-lg border border-border p-5"
                            key={section.title}
                          >
                            <p className="mb-3 text-sm font-medium">
                              {section.title}
                            </p>
                            <EvidenceList
                              empty="No entries recorded."
                              items={section.items}
                            />
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="grid gap-4 lg:grid-cols-3">
                      <div className="rounded-lg border border-border p-5">
                        <p className="mb-3 text-sm font-medium">Assumptions</p>
                        <EvidenceList
                          empty="No assumptions recorded."
                          items={execution.opinion.assumptions}
                        />
                      </div>
                      <div className="rounded-lg border border-border p-5">
                        <p className="mb-3 text-sm font-medium">Evidence gaps</p>
                        <EvidenceList
                          empty="No gaps recorded."
                          items={execution.opinion.gaps.map(
                            (gap) => `${gap.description} Required: ${gap.requiredEvidence}`,
                          )}
                        />
                      </div>
                      <div className="rounded-lg border border-border p-5">
                        <p className="mb-3 text-sm font-medium">
                          Invalidation signals
                        </p>
                        <EvidenceList
                          empty="No invalidation signals recorded."
                          items={execution.opinion.invalidationSignals}
                        />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
