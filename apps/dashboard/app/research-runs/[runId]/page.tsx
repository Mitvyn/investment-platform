import {
  ArrowLeft,
  Check,
  CircleDollarSign,
  Clock,
  ExternalLink,
  FileText,
  Fingerprint,
  LockKeyhole,
  ListChecks,
  Target,
  X,
} from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CommitteeMemoPanel } from "@/components/committee-memo-panel";
import { GraderCommitteePanel } from "@/components/grader-committee-panel";
import { GraderExecutionPanel } from "@/components/grader-execution-panel";
import { OperatorDecisionPanel } from "@/components/operator-decision-panel";
import { ReadinessThesisPanel } from "@/components/readiness-thesis-panel";
import { SystemModelCostsPanel } from "@/components/system-model-costs-panel";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { presentModelCostWorkspace } from "../../../lib/model-cost-workspace";
import { loadModelCosts } from "../../../lib/model-costs";
import { loadResearchRunFlow } from "../../../lib/research-run-flow";
import { loadResearchRun } from "../../../lib/research-runs";
import {
  presentResearchRunState,
  resolveResearchRunWorkspace,
  type ResearchRunWorkspaceField,
} from "../../../lib/research-run-workspace";
import { createClient } from "../../../lib/supabase/server";

export const dynamic = "force-dynamic";

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function AuditFieldList({
  dateLabels = [],
  fields,
}: {
  dateLabels?: string[];
  fields: ResearchRunWorkspaceField[];
}) {
  return (
    <dl className="grid gap-0">
      {fields.map((field, index) => (
        <div key={field.label}>
          {index > 0 ? <Separator /> : null}
          <div className="grid min-w-0 gap-1 py-4 sm:grid-cols-[8.5rem_minmax(0,1fr)] sm:gap-5">
            <dt className="text-xs font-medium text-muted-foreground">
              {field.label}
            </dt>
            <dd className="min-w-0 font-mono text-xs leading-5 text-foreground [overflow-wrap:anywhere] sm:text-right">
              {dateLabels.includes(field.label)
                ? formatDateTime(field.value)
                : field.value}
            </dd>
          </div>
        </div>
      ))}
    </dl>
  );
}

export default async function ResearchRunWorkspace({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  const { runId } = await params;
  const resolution = await resolveResearchRunWorkspace({
    operatorId:
      !error && typeof data?.claims?.sub === "string"
        ? data.claims.sub
        : null,
    runId,
    loadRun: loadResearchRun,
  });
  if (resolution.kind === "redirect") redirect(resolution.location);
  if (resolution.kind === "not_found") notFound();

  const run = resolution.run;
  const modelCosts = await loadModelCosts(run.operator_id, run.id);
  const modelCostPresentation = presentModelCostWorkspace(modelCosts);
  const projection = await loadResearchRunFlow(run.operator_id, run.id);
  if (projection === null) notFound();
  const {
    evidence: bundlePresentation,
    valuation: valuationPresentation,
    graders: graderPresentation,
    committee: committeePresentation,
    memo: memoPresentation,
    readinessThesis: readinessPresentation,
    operatorDecisions: operatorDecisionPresentation,
  } = projection.stages;
  const fields = projection.fields;
  const eligibility = projection.eligibility;
  const EligibilityIcon = run.eligibility.eligible ? Check : X;

  return (
    <main className="min-h-screen bg-background text-foreground">
      <nav className="border-b border-border/80" aria-label="Research Run">
        <div className="mx-auto flex min-h-16 max-w-[1600px] items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <Button asChild size="sm" variant="ghost">
            <Link href="/">
              <ArrowLeft aria-hidden="true" />
              Ticker workspace
            </Link>
          </Button>
          <Badge variant="outline">Authenticated audit workspace</Badge>
        </div>
      </nav>

      <div className="mx-auto grid max-w-[1600px] gap-8 px-4 py-8 sm:px-6 sm:py-10 lg:px-8 lg:py-12">
        <header className="grid gap-6 border-b border-border/80 pb-8 lg:grid-cols-[minmax(0,1fr)_minmax(17rem,22rem)] lg:items-end">
          <div className="min-w-0">
            <p className="mb-3 font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
              Versioned research question
            </p>
            <h1 className="font-mono text-5xl font-medium tracking-[-0.06em] sm:text-6xl">
              {run.security_identity.symbol}
            </h1>
            <p className="mt-3 max-w-3xl font-serif text-2xl leading-tight text-muted-foreground sm:text-3xl">
              {run.security_identity.issuer_name}
            </p>
          </div>

          <Card className="bg-card/70" aria-label="Historical eligibility">
            <CardContent className="flex min-w-0 items-center justify-between gap-4 p-5 sm:p-6">
              <div className="min-w-0">
                <p className="text-xs font-medium text-muted-foreground">
                  Historical eligibility
                </p>
                <p className="mt-2 font-mono text-xs [overflow-wrap:anywhere]">
                  {run.eligibility.policy_version}
                </p>
              </div>
              <Badge className="shrink-0" variant={eligibility.variant}>
                <EligibilityIcon aria-hidden="true" />
                {eligibility.label}
              </Badge>
            </CardContent>
          </Card>
        </header>

        <section
          className="grid gap-4 xl:grid-cols-3"
          aria-label="Research Run identity"
        >
          <Card>
            <CardHeader>
              <div className="mb-2 flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                <Fingerprint aria-hidden="true" className="size-4" />
              </div>
              <CardTitle>Stable identity</CardTitle>
              <CardDescription>
                Immutable identifiers for this security and run.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <AuditFieldList fields={fields.identity} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="mb-2 flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                <FileText aria-hidden="true" className="size-4" />
              </div>
              <CardTitle>Question contract</CardTitle>
              <CardDescription>
                Versions and cutoff that bound the research question.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <AuditFieldList dateLabels={["Cutoff"]} fields={fields.contract} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="mb-2 flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                <Clock aria-hidden="true" className="size-4" />
              </div>
              <CardTitle>Audit identity</CardTitle>
              <CardDescription>
                Persistence, status, and policy provenance.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <AuditFieldList dateLabels={["Created"]} fields={fields.audit} />
            </CardContent>
          </Card>
        </section>

        <Card aria-label="Operator focus">
          <CardHeader>
            <div className="mb-2 flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Target aria-hidden="true" className="size-4" />
            </div>
            <CardTitle>Operator focus</CardTitle>
            <CardDescription>
              Optional emphasis captured without changing the versioned contract.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="max-w-4xl text-sm leading-7">
              {run.operator_focus_normalized ?? "No additional focus supplied."}
            </p>
            {run.operator_focus_original !== run.operator_focus_normalized ? (
              <details className="mt-5 rounded-lg border border-border bg-muted/40 p-4 open:bg-muted/60">
                <summary className="cursor-pointer rounded-sm text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
                  Original input
                </summary>
                <pre className="mt-4 max-w-full overflow-x-auto whitespace-pre-wrap break-words border-t border-border pt-4 font-mono text-xs leading-6 text-muted-foreground">
                  {run.operator_focus_original}
                </pre>
              </details>
            ) : null}
          </CardContent>
        </Card>

        <section className="grid gap-5" aria-labelledby="eligibility-heading">
          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
            <div>
              <p className="mb-2 flex items-center gap-2 font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
                <ListChecks aria-hidden="true" className="size-4" />
                Historical eligibility
              </p>
              <h2
                className="font-serif text-3xl font-medium tracking-tight sm:text-4xl"
                id="eligibility-heading"
              >
                Rule-by-rule evidence at cutoff
              </h2>
            </div>
            <p className="font-mono text-xs text-muted-foreground">
              Evaluated {formatDateTime(run.eligibility.evaluated_at)}
            </p>
          </div>

          <ol className="grid list-none gap-4 p-0">
            {run.eligibility.checks.map((check) => {
              const result = presentResearchRunState(check.passed, "check");
              const ResultIcon = check.passed ? Check : X;

              return (
                <li className="min-w-0" key={check.rule_id}>
                  <Card>
                    <CardHeader className="gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
                      <div className="min-w-0">
                        <p className="font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                          {check.rule_version}
                        </p>
                        <CardTitle className="mt-2 capitalize [overflow-wrap:anywhere]">
                          {check.rule_id.replaceAll("_", " ")}
                        </CardTitle>
                        <CardDescription className="mt-3 max-w-4xl text-foreground/80">
                          {check.explanation}
                        </CardDescription>
                      </div>
                      <Badge variant={result.variant}>
                        <ResultIcon aria-hidden="true" />
                        {result.label}
                      </Badge>
                    </CardHeader>
                    <CardContent>
                      <dl className="grid gap-px overflow-hidden rounded-lg border border-border bg-border md:grid-cols-3">
                        <div className="min-w-0 bg-card p-4">
                          <dt className="text-xs font-medium text-muted-foreground">
                            Result
                          </dt>
                          <dd className="mt-2 text-sm font-medium">{result.label}</dd>
                        </div>
                        <div className="min-w-0 bg-card p-4">
                          <dt className="text-xs font-medium text-muted-foreground">
                            Reason code
                          </dt>
                          <dd className="mt-2 font-mono text-xs leading-5 [overflow-wrap:anywhere]">
                            {check.reason_code}
                          </dd>
                        </div>
                        <div className="min-w-0 bg-card p-4">
                          <dt className="text-xs font-medium text-muted-foreground">
                            Evidence
                          </dt>
                          <dd className="mt-2 font-mono text-xs leading-5 [overflow-wrap:anywhere]">
                            {check.evidence_reference ?? "Missing"}
                          </dd>
                        </div>
                      </dl>
                    </CardContent>
                  </Card>
                </li>
              );
            })}
          </ol>
        </section>

        <section className="grid gap-5" aria-labelledby="evidence-bundle-heading">
          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
            <div>
              <p className="mb-2 flex items-center gap-2 font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
                <LockKeyhole aria-hidden="true" className="size-4" />
                Frozen evidence
              </p>
              <h2
                className="font-serif text-3xl font-medium tracking-tight sm:text-4xl"
                id="evidence-bundle-heading"
              >
                Reproducibility manifest
              </h2>
            </div>
            <Badge variant={bundlePresentation.status.variant}>
              {bundlePresentation.status.label}
            </Badge>
          </div>

          {bundlePresentation.kind === "missing" ? (
            <Card className="border-warning/35 bg-warning-muted/10">
              <CardHeader>
                <CardTitle>Evidence Bundle unavailable</CardTitle>
                <CardDescription>
                  {bundlePresentation.description}
                </CardDescription>
              </CardHeader>
            </Card>
          ) : (
            <>
              <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
                <Card aria-label="Evidence Bundle audit identity">
                  <CardHeader>
                    <div className="mb-2 flex size-9 items-center justify-center rounded-md bg-evidence-muted text-evidence-muted-foreground">
                      <Fingerprint aria-hidden="true" className="size-4" />
                    </div>
                    <CardTitle>Content-addressed snapshot</CardTitle>
                    <CardDescription>
                      Exact persisted identity and policy versions for this frozen
                      evidence set.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <AuditFieldList fields={bundlePresentation.summary} />
                  </CardContent>
                </Card>

                <Card aria-label="Evidence Bundle readiness">
                  <CardHeader>
                    <div className="mb-2 flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                      {bundlePresentation.readiness.variant === "verified" ? (
                        <Check aria-hidden="true" className="size-4" />
                      ) : (
                        <X aria-hidden="true" className="size-4" />
                      )}
                    </div>
                    <CardTitle>Grader readiness</CardTitle>
                    <CardDescription>
                      Blocking primary-evidence requirements only. No analytical
                      verdict is implied.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="grid gap-4">
                    <Badge
                      className="w-fit"
                      variant={bundlePresentation.readiness.variant}
                    >
                      {bundlePresentation.readiness.label}
                    </Badge>
                    <p className="text-sm leading-6 text-muted-foreground">
                      {bundlePresentation.readiness.description}
                    </p>
                  </CardContent>
                </Card>
              </div>

              {bundlePresentation.gaps.length > 0 ? (
                <div className="grid gap-3" aria-label="Blocking evidence gaps">
                  {bundlePresentation.gaps.map((gap) => (
                    <Card
                      className="border-challenge/35 bg-challenge-muted/10"
                      key={gap.id}
                    >
                      <CardHeader className="gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
                        <div className="min-w-0">
                          <p className="font-mono text-[11px] text-challenge-muted-foreground [overflow-wrap:anywhere]">
                            {gap.id}
                          </p>
                          <CardTitle className="mt-2 [overflow-wrap:anywhere]">
                            {gap.requirement.replaceAll("_", " ")}
                          </CardTitle>
                          <CardDescription className="mt-3 text-foreground/80">
                            {gap.explanation}
                          </CardDescription>
                        </div>
                        <Badge variant="destructive">{gap.sourceClass}</Badge>
                      </CardHeader>
                      <CardContent>
                        <p className="font-mono text-xs text-challenge-muted-foreground [overflow-wrap:anywhere]">
                          {gap.reason}
                        </p>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              ) : null}

              <ol className="grid list-none gap-4 p-0" aria-label="Ordered evidence manifest">
                {bundlePresentation.manifest.map((item) => (
                  <li className="min-w-0" key={item.fields[0].value}>
                    <Card>
                      <CardHeader className="gap-5 lg:grid-cols-[4rem_minmax(0,1fr)_auto] lg:items-start">
                        <div className="flex size-12 items-center justify-center rounded-lg border border-evidence/35 bg-evidence-muted font-mono text-sm font-medium text-evidence-muted-foreground">
                          {item.ordinal}
                        </div>
                        <div className="min-w-0">
                          <p className="font-mono text-[11px] tracking-[0.08em] text-muted-foreground uppercase">
                            {item.sourceClass} source
                          </p>
                          <CardTitle className="mt-2">{item.itemKind}</CardTitle>
                          <Button
                            asChild
                            className="mt-4 max-w-full"
                            size="sm"
                            variant="outline"
                          >
                            <a
                              aria-label={`Open ${item.sourceClass} source for manifest item ${item.ordinal}`}
                              href={item.sourceUrl}
                              rel="noreferrer"
                              target="_blank"
                            >
                              <ExternalLink aria-hidden="true" />
                              Open primary source
                            </a>
                          </Button>
                        </div>
                        <Badge variant={item.freshness.variant}>
                          {item.freshness.label}
                        </Badge>
                      </CardHeader>
                      <CardContent>
                        <AuditFieldList fields={item.fields} />
                      </CardContent>
                    </Card>
                  </li>
                ))}
              </ol>
            </>
          )}
        </section>

        <section className="grid gap-5" aria-labelledby="valuation-heading">
          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
            <div>
              <p className="mb-2 flex items-center gap-2 font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
                <CircleDollarSign aria-hidden="true" className="size-4" />
                Point-in-time valuation
              </p>
              <h2
                className="font-serif text-3xl font-medium tracking-tight sm:text-4xl"
                id="valuation-heading"
              >
                Market value at cutoff
              </h2>
            </div>
            <Badge variant={valuationPresentation.status.variant}>
              {valuationPresentation.status.label}
            </Badge>
          </div>

          {valuationPresentation.kind === "missing" ? (
            <Card className="border-warning/35 bg-warning-muted/10">
              <CardHeader>
                <CardTitle>Valuation Snapshot unavailable</CardTitle>
                <CardDescription>
                  {valuationPresentation.description}
                </CardDescription>
              </CardHeader>
            </Card>
          ) : (
            <>
              <Card aria-label="Information alignment">
                <CardHeader className="gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
                  <div>
                    <CardTitle>Information alignment</CardTitle>
                    <CardDescription className="mt-2 max-w-3xl">
                      {valuationPresentation.alignment.description}
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant={valuationPresentation.alignment.variant}>
                      {valuationPresentation.alignment.label}
                    </Badge>
                    <Badge
                      variant={
                        valuationPresentation.marketRelativeAnalysis.variant
                      }
                    >
                      {valuationPresentation.marketRelativeAnalysis.label}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <dl className="grid gap-px overflow-hidden rounded-lg border border-border bg-border md:grid-cols-4">
                    <div className="min-w-0 bg-card p-4">
                      <dt className="text-xs font-medium text-muted-foreground">
                        Evidence cutoff
                      </dt>
                      <dd className="mt-2 font-mono text-xs leading-5 [overflow-wrap:anywhere]">
                        {valuationPresentation.snapshot.as_of_cutoff}
                      </dd>
                    </div>
                    <div className="min-w-0 bg-card p-4">
                      <dt className="text-xs font-medium text-muted-foreground">
                        Market session
                      </dt>
                      <dd className="mt-2 font-mono text-xs leading-5 [overflow-wrap:anywhere]">
                        {valuationPresentation.snapshot.price_basis?.session_date ??
                          "Unavailable"}
                      </dd>
                    </div>
                    <div className="min-w-0 bg-card p-4">
                      <dt className="text-xs font-medium text-muted-foreground">
                        Evidence Bundle
                      </dt>
                      <dd className="mt-2 font-mono text-xs leading-5 [overflow-wrap:anywhere]">
                        {valuationPresentation.snapshot.evidence_bundle_hash}
                      </dd>
                    </div>
                    <div className="min-w-0 bg-card p-4">
                      <dt className="text-xs font-medium text-muted-foreground">
                        Alignment state
                      </dt>
                      <dd className="mt-2 font-mono text-xs leading-5 [overflow-wrap:anywhere]">
                        {valuationPresentation.snapshot.price_information_state}
                      </dd>
                    </div>
                  </dl>
                </CardContent>
              </Card>

              {valuationPresentation.invalidReasons.length > 0 ? (
                <div className="grid gap-3" aria-label="Invalid valuation reasons">
                  {valuationPresentation.invalidReasons.map((reason) => (
                    <Card
                      className="border-challenge/35 bg-challenge-muted/10"
                      key={reason.code}
                    >
                      <CardContent className="grid gap-2 p-5 sm:p-6">
                        <p className="font-medium capitalize">{reason.label}</p>
                        <p className="font-mono text-xs text-challenge-muted-foreground [overflow-wrap:anywhere]">
                          {reason.code}
                        </p>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              ) : null}

              {valuationPresentation.assurance !== null ? (
                <Card
                  aria-label="Personal research valuation assurance"
                  className="border-warning/35 bg-warning-muted/10"
                >
                  <CardHeader>
                    <CardTitle>{valuationPresentation.assurance.label}</CardTitle>
                    <CardDescription>
                      {valuationPresentation.assurance.description}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <AuditFieldList
                      fields={[
                        {
                          label: "Usage scope",
                          value: valuationPresentation.assurance.usageScope,
                        },
                        {
                          label: "Rights assurance",
                          value: valuationPresentation.assurance.rightsAssurance,
                        },
                        {
                          label: "Limitations",
                          value:
                            valuationPresentation.assurance.limitationCodes.join(
                              ", ",
                            ),
                        },
                      ]}
                    />
                  </CardContent>
                </Card>
              ) : null}

              <div className="grid gap-4 xl:grid-cols-2">
                <Card aria-label="Valuation Snapshot identity">
                  <CardHeader>
                    <CardTitle>Snapshot identity</CardTitle>
                    <CardDescription>
                      Persisted valuation identity, evidence link, and policy
                      versions.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <AuditFieldList fields={valuationPresentation.summary} />
                  </CardContent>
                </Card>

                <Card
                  aria-label={
                    valuationPresentation.assurance === null
                      ? "Official close price basis"
                      : "Consolidated EOD price basis"
                  }
                >
                  <CardHeader>
                    <CardTitle>
                      {valuationPresentation.assurance === null
                        ? "Official close"
                        : "Consolidated EOD price"}
                    </CardTitle>
                    <CardDescription>
                      {valuationPresentation.assurance === null
                        ? "Latest completed regular US trading session permitted by policy."
                        : "Verified personal-research close for latest completed regular US trading session."}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {valuationPresentation.priceBasis === null ? (
                      <div className="rounded-lg border border-challenge/35 bg-challenge-muted/10 p-4">
                        <p className="text-sm text-challenge-muted-foreground">
                          {valuationPresentation.assurance === null
                            ? "No valid official close is available for this snapshot."
                            : "No valid consolidated EOD price is available for this snapshot."}
                        </p>
                      </div>
                    ) : (
                      <div className="grid gap-5">
                        <p className="font-mono text-3xl font-medium tracking-tight text-evidence-muted-foreground">
                          {valuationPresentation.priceBasis.headline}
                        </p>
                        <AuditFieldList
                          fields={valuationPresentation.priceBasis.fields}
                        />
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>

              <section className="grid gap-4" aria-labelledby="capital-inputs-heading">
                <div>
                  <p className="font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
                    Filing-backed inputs
                  </p>
                  <h3
                    className="mt-2 font-serif text-2xl font-medium"
                    id="capital-inputs-heading"
                  >
                    Capital structure
                  </h3>
                </div>
                <div className="grid gap-4 lg:grid-cols-2">
                  {valuationPresentation.capitalInputs.map((input) => (
                    <Card key={input.label}>
                      <CardHeader>
                        <CardTitle>{input.label}</CardTitle>
                        <CardDescription className="font-mono text-lg text-foreground">
                          {input.value} {input.unit}
                        </CardDescription>
                      </CardHeader>
                      <CardContent>
                        <AuditFieldList fields={input.fields} />
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </section>

              {valuationPresentation.dilutionInstruments.length > 0 ? (
                <Card aria-label="Dilution instruments">
                  <CardHeader>
                    <CardTitle>Dilution instruments</CardTitle>
                    <CardDescription>
                      Filing-derived increments included in fully diluted shares.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="grid gap-px overflow-hidden rounded-lg border border-border bg-border md:grid-cols-4">
                      {valuationPresentation.dilutionInstruments.map(
                        (instrument) => (
                          <div className="min-w-0 bg-card p-4" key={instrument.id}>
                            <p className="text-xs font-medium capitalize text-muted-foreground">
                              {instrument.type}
                            </p>
                            <p className="mt-2 font-mono text-sm [overflow-wrap:anywhere]">
                              +{instrument.increment} shares
                            </p>
                            <p className="mt-2 font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                              {instrument.effective}
                            </p>
                            <p className="mt-2 font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                              {instrument.evidenceIds.join(", ")}
                            </p>
                          </div>
                        ),
                      )}
                    </div>
                  </CardContent>
                </Card>
              ) : null}

              <div className="grid gap-4 lg:grid-cols-2" aria-label="Derived valuation calculations">
                {valuationPresentation.derivedValues.map((value) => (
                  <Card key={value.calculationId}>
                    <CardHeader>
                      <CardTitle>{value.label}</CardTitle>
                      <CardDescription className="font-mono text-2xl text-foreground">
                        {value.value}
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <AuditFieldList
                        fields={[
                          { label: "Formula", value: value.formula },
                          {
                            label: "Formula version",
                            value: value.formulaVersion,
                          },
                          {
                            label: "Calculation ID",
                            value: value.calculationId,
                          },
                          {
                            label: "Input IDs",
                            value: value.inputIds.join(", "),
                          },
                          {
                            label: "Evidence IDs",
                            value: value.evidenceIds.join(", "),
                          },
                        ]}
                      />
                    </CardContent>
                  </Card>
                ))}
              </div>

              <Card aria-label="Corporate action reconciliation">
                <CardHeader>
                  <CardTitle>Corporate-action reconciliation</CardTitle>
                  <CardDescription>
                    Confirms price and share-count inputs represent same economic
                    state.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <AuditFieldList
                    fields={[
                      { label: "Event", value: valuationPresentation.corporateAction.event },
                      {
                        label: "Event ID",
                        value: valuationPresentation.corporateAction.eventId,
                      },
                      {
                        label: "Effective",
                        value: valuationPresentation.corporateAction.effective,
                      },
                      {
                        label: "Price adjustment",
                        value: valuationPresentation.corporateAction.priceAdjustment,
                      },
                      {
                        label: "Share-count adjustment",
                        value:
                          valuationPresentation.corporateAction.shareCountAdjustment,
                      },
                      {
                        label: "Result",
                        value: valuationPresentation.corporateAction.result,
                      },
                    ]}
                  />
                </CardContent>
              </Card>

              <div className="grid gap-4 xl:grid-cols-2">
                <Card aria-label="Valuation source references">
                  <CardHeader>
                    <CardTitle>Source references</CardTitle>
                    <CardDescription>
                      {valuationPresentation.assurance === null
                        ? "Licensed market source and primary filing provenance."
                        : "Personal market source and primary filing provenance."}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="grid gap-4">
                    {valuationPresentation.sourceReferences.map((source) => (
                      <div
                        className={
                          "providerProvenanceVariant" in source
                            ? "rounded-lg border border-warning/35 bg-warning-muted/10 p-4"
                            : "rounded-lg border border-border p-4"
                        }
                        key={source.id}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-medium">{source.provider}</p>
                          {"providerProvenanceVariant" in source ? (
                            <Badge variant="attention">Provider caveat</Badge>
                          ) : null}
                        </div>
                        <p className="mt-1 font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                          {source.type} · {source.id}
                        </p>
                        <p className="mt-3 text-sm [overflow-wrap:anywhere]">
                          {source.locator}
                        </p>
                        <dl className="mt-4 grid gap-3 text-xs text-muted-foreground sm:grid-cols-3">
                          <div>
                            <dt>Published</dt>
                            <dd className="mt-1 font-mono [overflow-wrap:anywhere]">
                              {source.published}
                            </dd>
                          </div>
                          <div>
                            <dt>Retrieved</dt>
                            <dd className="mt-1 font-mono [overflow-wrap:anywhere]">
                              {source.retrieved}
                            </dd>
                          </div>
                          <div>
                            <dt>Effective</dt>
                            <dd className="mt-1 font-mono [overflow-wrap:anywhere]">
                              {source.effective}
                            </dd>
                          </div>
                          {"providerPlan" in source ? (
                            <div>
                              <dt>Provider plan</dt>
                              <dd className="mt-1 font-mono [overflow-wrap:anywhere]">
                                {source.providerPlan}
                              </dd>
                            </div>
                          ) : null}
                          {"providerContractStatus" in source ? (
                            <div>
                              <dt>Provider contract status</dt>
                              <dd className="mt-1 font-mono text-warning-muted-foreground [overflow-wrap:anywhere]">
                                {source.providerContractStatus}
                              </dd>
                            </div>
                          ) : null}
                          {"providerLimitationCodes" in source ? (
                            <div className="sm:col-span-3">
                              <dt>Provider limitations</dt>
                              <dd className="mt-1 font-mono text-warning-muted-foreground [overflow-wrap:anywhere]">
                                {source.providerLimitationCodes?.join(", ") ??
                                  "None declared"}
                              </dd>
                            </div>
                          ) : null}
                          {"responseSha256" in source ? (
                            <div>
                              <dt>Response hash</dt>
                              <dd className="mt-1 font-mono [overflow-wrap:anywhere]">
                                {source.responseSha256}
                              </dd>
                            </div>
                          ) : null}
                        </dl>
                      </div>
                    ))}
                  </CardContent>
                </Card>

                <Card aria-label="Market materiality classifications">
                  <CardHeader>
                    <CardTitle>Evidence timing and materiality</CardTitle>
                    <CardDescription>
                      Deterministic classifications used for price-information
                      alignment.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="grid gap-4">
                    {valuationPresentation.materiality.map((item) => (
                      <div
                        className="rounded-lg border border-border p-4"
                        key={item.evidenceId}
                      >
                        <div className="flex flex-wrap gap-2">
                          <Badge
                            variant={
                              item.materiality === "material"
                                ? "attention"
                                : "outline"
                            }
                          >
                            {item.materiality}
                          </Badge>
                          <Badge variant="outline">{item.timing}</Badge>
                        </div>
                        <p className="mt-3 font-mono text-xs [overflow-wrap:anywhere]">
                          {item.evidenceId}
                        </p>
                        <p className="mt-2 font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                          {item.reason}
                        </p>
                        <p className="mt-2 text-xs text-muted-foreground">
                          {item.domains.join(", ")}
                        </p>
                        <p className="mt-2 font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                          {item.policy} · {item.published}
                        </p>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </section>

        <GraderCommitteePanel presentation={committeePresentation} />

        <CommitteeMemoPanel presentation={memoPresentation} />

        <ReadinessThesisPanel presentation={readinessPresentation} />

        <OperatorDecisionPanel presentation={operatorDecisionPresentation} />

        <GraderExecutionPanel presentation={graderPresentation} />

        <SystemModelCostsPanel presentation={modelCostPresentation} />
      </div>
    </main>
  );
}
