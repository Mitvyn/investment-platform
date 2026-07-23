import { BrainCircuit, FileCheck2, Scale, ShieldAlert } from "lucide-react";

import type { presentGraderCommitteeWorkspace } from "@/lib/grader-committee-workspace";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type Presentation = ReturnType<typeof presentGraderCommitteeWorkspace>;

function DetailList({ empty, items }: { empty: string; items: string[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{empty}</p>;
  }
  return (
    <ul className="grid list-disc gap-2 pl-5 text-sm leading-6">
      {items.map((item) => (
        <li className="[overflow-wrap:anywhere]" key={item}>
          {item}
        </li>
      ))}
    </ul>
  );
}

export function GraderCommitteePanel({
  presentation,
}: {
  presentation: Presentation;
}) {
  const counts = [
    ["Eligible", presentation.counts.eligible],
    ["Accepted", presentation.counts.accepted],
    ["Abstained", presentation.counts.abstained],
    ["Failed", presentation.counts.failed],
    ["Not eligible", presentation.counts.notEligible],
    ["Not executed", presentation.counts.notExecuted],
  ] as const;
  const stances = [
    ["Supports", presentation.agreement.supports],
    ["Mixed", presentation.agreement.mixed],
    ["Challenges", presentation.agreement.challenges],
  ] as const;

  return (
    <section className="grid gap-5" aria-labelledby="committee-heading">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="mb-2 flex items-center gap-2 font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
            <BrainCircuit aria-hidden="true" className="size-4" />
            Research committee
          </p>
          <h2
            className="font-serif text-3xl font-medium tracking-tight sm:text-4xl"
            id="committee-heading"
          >
            Five independent grader views
          </h2>
        </div>
        <Badge variant={presentation.status.variant}>
          {presentation.status.label}
        </Badge>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
        <Card aria-label="Committee state accounting">
          <CardHeader>
            <FileCheck2 aria-hidden="true" className="size-5 text-primary" />
            <CardTitle>Execution-state accounting</CardTitle>
            <CardDescription>
              Every roster state stays explicit. Abstention, failure, ineligibility,
              and unavailable execution are not neutral opinions.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-3">
              {counts.map(([label, value]) => (
                <div className="bg-card p-4" key={label}>
                  <dt className="text-xs font-medium text-muted-foreground">
                    {label}
                  </dt>
                  <dd className="mt-2 font-mono text-2xl font-medium">{value}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>

        <Card aria-label="Accepted opinion stance accounting">
          <CardHeader>
            <Scale aria-hidden="true" className="size-5 text-primary" />
            <CardTitle>Directional stance</CardTitle>
            <CardDescription>
              Accepted compatible opinions only. Counts explain disagreement;
              they do not decide disposition.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            {stances.map(([label, value]) => (
              <div
                className="flex items-center justify-between gap-4 rounded-lg border border-border px-4 py-3"
                key={label}
              >
                <span className="text-sm font-medium">{label}</span>
                <span className="font-mono text-sm">
                  {value} / {presentation.agreement.denominator}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card aria-label="Shared proposition stance matrix">
        <CardHeader>
          <CardTitle>Shared-proposition stance matrix</CardTitle>
          <CardDescription>
            Same frozen evidence bundle and proposition; separate owned decision
            questions. Nonaccepted results produce no stance.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5">
          <div className="rounded-lg border border-primary/25 bg-primary/5 p-4 sm:p-5">
            <p className="font-mono text-[11px] text-primary [overflow-wrap:anywhere]">
              {presentation.proposition.id} · {presentation.proposition.version}
            </p>
            <p className="mt-3 font-serif text-lg leading-relaxed sm:text-xl">
              {presentation.proposition.text}
            </p>
          </div>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-[48rem] border-collapse text-left text-sm">
              <thead className="bg-muted/60 text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 font-medium">Grader</th>
                  <th className="px-4 py-3 font-medium">Owned question</th>
                  <th className="px-4 py-3 font-medium">Execution state</th>
                  <th className="px-4 py-3 font-medium">Stance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {presentation.rows.map((row) => (
                  <tr className="align-top" key={row.graderId}>
                    <th className="px-4 py-4 font-medium">{row.label}</th>
                    <td className="max-w-xl px-4 py-4 leading-6 text-muted-foreground">
                      {row.ownedQuestion}
                    </td>
                    <td className="px-4 py-4">
                      <Badge variant={row.state.variant}>{row.state.label}</Badge>
                    </td>
                    <td className="px-4 py-4">
                      {row.stance === null ? (
                        <span className="font-mono text-xs text-muted-foreground">
                          No stance
                        </span>
                      ) : (
                        <Badge variant={row.stance.variant}>
                          {row.stance.label}
                        </Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4" aria-label="Committee grader opinions">
        {presentation.rows.map((row) => (
          <Card key={row.graderId}>
            <CardHeader className="gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
              <div className="min-w-0">
                <p className="font-mono text-[11px] tracking-[0.08em] text-primary uppercase">
                  {row.version ?? `${row.graderId}.v1`}
                </p>
                <CardTitle className="mt-2">{row.label} grader</CardTitle>
                <CardDescription className="mt-2 max-w-4xl text-foreground/80">
                  {row.ownedQuestion}
                </CardDescription>
              </div>
              <div className="flex flex-wrap gap-2 lg:justify-end">
                <Badge variant={row.state.variant}>{row.state.label}</Badge>
                {row.stance ? (
                  <Badge variant={row.stance.variant}>{row.stance.label}</Badge>
                ) : null}
                {row.confidence ? (
                  <Badge variant="outline">Confidence {row.confidence}</Badge>
                ) : null}
              </div>
            </CardHeader>
            <CardContent className="grid gap-5">
              {row.opinionId ? (
                <p className="font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                  Opinion {row.opinionId}
                </p>
              ) : null}
              {row.summary ? (
                <p className="max-w-5xl text-sm leading-7">{row.summary}</p>
              ) : null}

              {row.claims.length > 0 ? (
                <div className="grid gap-3" aria-label={`${row.label} material claims`}>
                  {row.claims.map((claim) => (
                    <div
                      className="rounded-lg border border-evidence/30 bg-evidence-muted/15 p-4"
                      key={`${row.graderId}-${claim.claim}`}
                    >
                      <p className="text-sm leading-6">{claim.claim}</p>
                      <p className="mt-3 font-mono text-[11px] text-evidence-muted-foreground [overflow-wrap:anywhere]">
                        {claim.evidenceIds.join(", ")}
                      </p>
                    </div>
                  ))}
                </div>
              ) : null}

              {row.reason ? (
                <div
                  className={
                    row.stateCode === "accepted"
                      ? "rounded-lg border border-primary/25 bg-primary/5 p-4"
                      : row.stateCode === "failed"
                        ? "rounded-lg border border-challenge/35 bg-challenge-muted/10 p-4"
                        : "rounded-lg border border-warning/35 bg-warning-muted/10 p-4"
                  }
                >
                  <p className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground uppercase">
                    <ShieldAlert aria-hidden="true" className="size-4" />
                    {row.stateCode === "accepted" ? "Stance rationale" : "Reason"}
                  </p>
                  <p className="text-sm leading-6">{row.reason}</p>
                </div>
              ) : null}

              <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-lg border border-evidence/30 bg-evidence-muted/15 p-4">
                  <p className="mb-3 text-sm font-medium">Validated citations</p>
                  <DetailList
                    empty="No citations for this execution state."
                    items={row.citations}
                  />
                </div>
                <div className="rounded-lg border border-border p-4">
                  <p className="mb-3 text-sm font-medium">Evidence gaps</p>
                  <DetailList empty="No evidence gaps recorded." items={row.gaps} />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
