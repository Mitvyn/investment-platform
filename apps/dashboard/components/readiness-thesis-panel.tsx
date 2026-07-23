import {
  AlertTriangle,
  CheckCircle2,
  FileSearch,
  GitBranch,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import type { ReadinessThesisPresentation } from "@/lib/readiness-thesis-workspace";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type Presentation = ReadinessThesisPresentation;
type Chain = Presentation["chain"];
type Version = Chain["canonicalVersions"][number];

function Identifier({ children }: { children: string | null }) {
  return (
    <span className="font-mono text-[11px] leading-5 [overflow-wrap:anywhere]">
      {children ?? "None"}
    </span>
  );
}

function VersionCard({ version }: { version: Version }) {
  return (
    <div className="grid gap-3 rounded-lg border border-border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <Identifier>{version.id}</Identifier>
        <Badge variant={version.status === "Canonical" ? "verified" : "attention"}>
          {version.status}
        </Badge>
      </div>
      <dl className="grid gap-3 text-xs sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground">Final disposition</dt>
          <dd className="mt-1">{version.finalDisposition}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Research Run</dt>
          <dd className="mt-1"><Identifier>{version.researchRunId}</Identifier></dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Previous canonical</dt>
          <dd className="mt-1"><Identifier>{version.previousCanonicalThesisVersionId}</Identifier></dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Based on thesis</dt>
          <dd className="mt-1"><Identifier>{version.basedOnThesisVersionId}</Identifier></dd>
        </div>
      </dl>
    </div>
  );
}

function ChainPanel({ chain }: { chain: Chain }) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card aria-label="Canonical thesis chain">
        <CardHeader>
          <GitBranch aria-hidden="true" className="size-5 text-primary" />
          <CardTitle>Canonical chain</CardTitle>
          <CardDescription>
            Ordered immutable versions. Active canonical: {chain.activeCanonicalThesisVersionId ?? "None"}.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {chain.canonicalVersions.length === 0 ? (
            <p className="text-sm text-muted-foreground">No canonical thesis exists.</p>
          ) : chain.canonicalVersions.map((version) => (
            <VersionCard key={version.id} version={version} />
          ))}
        </CardContent>
      </Card>

      <Card aria-label="Provisional thesis branches">
        <CardHeader>
          <GitBranch aria-hidden="true" className="size-5 text-warning-muted-foreground" />
          <CardTitle>Provisional branches</CardTitle>
          <CardDescription>
            Abstention-qualified versions remain branches and never supersede canonical history.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {chain.provisionalBranches.length === 0 ? (
            <p className="text-sm text-muted-foreground">No provisional branch exists.</p>
          ) : chain.provisionalBranches.map((version) => (
            <VersionCard key={version.id} version={version} />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

export function ReadinessThesisPanel({
  presentation,
}: {
  presentation: Presentation;
}) {
  if (presentation.kind === "missing") {
    return (
      <section className="grid gap-5" aria-labelledby="readiness-heading">
        <div>
          <p className="mb-2 font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
            Deterministic readiness
          </p>
          <h2 className="font-serif text-3xl font-medium tracking-tight sm:text-4xl" id="readiness-heading">
            Readiness and thesis history
          </h2>
        </div>
        <Card className="border-warning/35 bg-warning-muted/10">
          <CardHeader>
            <CardTitle>{presentation.title}</CardTitle>
            <CardDescription>{presentation.description}</CardDescription>
          </CardHeader>
        </Card>
        <ChainPanel chain={presentation.chain} />
      </section>
    );
  }

  const readinessVariant = presentation.readiness.failedCount === 0
    ? "verified" as const
    : "attention" as const;

  return (
    <section className="grid gap-5" aria-labelledby="readiness-heading">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="mb-2 flex items-center gap-2 font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
            <ShieldCheck aria-hidden="true" className="size-4" />
            Deterministic readiness
          </p>
          <h2 className="font-serif text-3xl font-medium tracking-tight sm:text-4xl" id="readiness-heading">
            Readiness and thesis history
          </h2>
        </div>
        <Badge variant={readinessVariant}>{presentation.readiness.status}</Badge>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Requested disposition</CardTitle>
            <CardDescription>Synthesizer recommendation before deterministic policy.</CardDescription>
          </CardHeader>
          <CardContent className="font-serif text-2xl">{presentation.readiness.requestedDisposition}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Final disposition</CardTitle>
            <CardDescription>Preserved or downgraded. Never upgraded.</CardDescription>
          </CardHeader>
          <CardContent className="font-serif text-2xl">{presentation.readiness.finalDisposition}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Readiness policy</CardTitle>
            <CardDescription>Immutable gate identity and evaluation.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2">
            <Identifier>{presentation.readiness.id}</Identifier>
            <Identifier>{presentation.readiness.policyVersion}</Identifier>
            <p className="text-xs text-muted-foreground">{presentation.readiness.evaluatedAt}</p>
          </CardContent>
        </Card>
      </div>

      <Card aria-label="Eleven readiness policy checks">
        <CardHeader>
          <FileSearch aria-hidden="true" className="size-5 text-primary" />
          <CardTitle>11 policy checks</CardTitle>
          <CardDescription>
            {presentation.readiness.passedCount} passed · {presentation.readiness.failedCount} failed
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ol className="grid list-none gap-3 p-0 lg:grid-cols-2">
            {presentation.readiness.checks.map((check) => {
              const passed = check.state === "passed";
              const Icon = passed ? CheckCircle2 : XCircle;
              return (
                <li className="grid gap-3 rounded-lg border border-border p-4" key={check.id}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-medium">{check.label}</p>
                      <p className="mt-1 font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">{check.version}</p>
                    </div>
                    <Badge variant={passed ? "verified" : "destructive"}>
                      <Icon aria-hidden="true" />{check.state}
                    </Badge>
                  </div>
                  <p className="text-sm leading-6 text-muted-foreground">{check.explanation}</p>
                  <p className="font-mono text-[11px] [overflow-wrap:anywhere]">{check.reasonCode}</p>
                  <p className="font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                    References: {check.referenceIds.join(", ") || "None"}
                  </p>
                </li>
              );
            })}
          </ol>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card aria-label="Readiness blocking reasons">
          <CardHeader>
            <AlertTriangle aria-hidden="true" className="size-5 text-warning-muted-foreground" />
            <CardTitle>Blocking reasons</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            {presentation.readiness.blockingReasons.length === 0 ? (
              <p className="text-sm text-muted-foreground">No readiness blocker recorded.</p>
            ) : presentation.readiness.blockingReasons.map((reason) => (
              <div className="rounded-lg border border-warning/35 bg-warning-muted/10 p-4" key={reason.code}>
                <p className="font-medium">{reason.explanation}</p>
                <p className="mt-2 font-mono text-[11px] [overflow-wrap:anywhere]">{reason.code} · {reason.checkId}</p>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card aria-label="Required next evidence">
          <CardHeader>
            <FileSearch aria-hidden="true" className="size-5 text-warning-muted-foreground" />
            <CardTitle>Required next evidence</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            {presentation.readiness.requiredNextEvidence.length === 0 ? (
              <p className="text-sm text-muted-foreground">No additional blocking evidence required.</p>
            ) : presentation.readiness.requiredNextEvidence.map((requirement) => (
              <div className="rounded-lg border border-border p-4" key={requirement.id}>
                <p className="font-medium">{requirement.description}</p>
                <p className="mt-2 font-mono text-[11px] [overflow-wrap:anywhere]">{requirement.id}</p>
                <p className="mt-2 text-xs text-muted-foreground">Checks: {requirement.affectedCheckIds.join(", ")}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card aria-label="Thesis creation outcome">
        <CardHeader className="gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
          <div>
            <CardTitle>Thesis creation outcome</CardTitle>
            <CardDescription className="mt-2">{presentation.thesis.reasonCode}</CardDescription>
          </div>
          <Badge variant={presentation.thesis.version?.status === "Provisional" ? "attention" : "verified"}>
            {presentation.thesis.outcome}
          </Badge>
        </CardHeader>
        <CardContent className="grid gap-4">
          <Identifier>{presentation.thesis.creationResultId}</Identifier>
          {presentation.thesis.version === null ? (
            <p className="text-sm text-muted-foreground">No thesis created for this incomplete committee result.</p>
          ) : (
            <VersionCard version={presentation.thesis.version} />
          )}
        </CardContent>
      </Card>

      <ChainPanel chain={presentation.chain} />
    </section>
  );
}
