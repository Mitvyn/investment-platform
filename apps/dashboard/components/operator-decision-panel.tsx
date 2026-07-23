import {
  FileClock,
  GitCommitHorizontal,
  History,
  Milestone,
  ShieldCheck,
} from "lucide-react";

import type { OperatorDecisionPresentation } from "@/lib/operator-decision-workspace";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

function Identifier({ children }: { children: string | null }) {
  return (
    <span className="font-mono text-[11px] leading-5 [overflow-wrap:anywhere]">
      {children ?? "None"}
    </span>
  );
}

export function OperatorDecisionPanel({
  presentation,
}: {
  presentation: OperatorDecisionPresentation;
}) {
  if (presentation.kind === "missing") {
    return (
      <section className="grid gap-5" aria-labelledby="operator-decisions-heading">
        <div>
          <p className="mb-2 font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
            Human response ledger
          </p>
          <h2
            className="font-serif text-3xl font-medium tracking-tight sm:text-4xl"
            id="operator-decisions-heading"
          >
            Operator decisions
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

  const relationshipVariant = presentation.current.relationship === "Override"
    ? "attention" as const
    : presentation.current.relationship === "Accept"
      ? "verified" as const
      : "outline" as const;

  return (
    <section className="grid gap-5" aria-labelledby="operator-decisions-heading">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="mb-2 flex items-center gap-2 font-mono text-[11px] font-medium tracking-[0.08em] text-primary uppercase">
            <History aria-hidden="true" className="size-4" />
            Human response ledger
          </p>
          <h2
            className="font-serif text-3xl font-medium tracking-tight sm:text-4xl"
            id="operator-decisions-heading"
          >
            Operator decisions
          </h2>
        </div>
        <Badge variant={relationshipVariant}>
          {presentation.current.relationship}
        </Badge>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
        <Card aria-label="Derived current operator state">
          <CardHeader>
            <ShieldCheck aria-hidden="true" className="size-5 text-primary" />
            <CardTitle>Derived current state</CardTitle>
            <CardDescription>
              Current operator state is derived from the latest valid event in the supersession chain.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div>
              <p className="text-xs text-muted-foreground">Action</p>
              <p className="mt-1 font-medium">{presentation.current.action}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Relationship</p>
              <p className="mt-1 font-medium">{presentation.current.relationship}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Current decision</p>
              <p className="mt-1"><Identifier>{presentation.current.decisionId}</Identifier></p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Supersession depth</p>
              <p className="mt-1 font-mono text-xs">{presentation.current.supersessionDepth}</p>
            </div>
            <p className="text-xs text-muted-foreground sm:col-span-2">
              Derived {presentation.current.derivedAt}
            </p>
          </CardContent>
        </Card>

        <Card className="border-primary/25 bg-primary/5">
          <CardHeader>
            <GitCommitHorizontal aria-hidden="true" className="size-5 text-primary" />
            <CardTitle>Research result remains unchanged</CardTitle>
            <CardDescription>
              Operator events record a response. They never relabel the committee disposition, readiness result, or thesis.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>

      <Card aria-label="Append-only operator decision history">
        <CardHeader>
          <FileClock aria-hidden="true" className="size-5 text-primary" />
          <CardTitle>Append-only history</CardTitle>
          <CardDescription>
            {presentation.history.length} immutable event{presentation.history.length === 1 ? "" : "s"}, oldest first.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ol className="grid list-none gap-4 p-0">
            {presentation.history.map((event) => (
              <li className="grid gap-4 rounded-lg border border-border p-4" key={event.decisionId}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-medium">{event.action}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      System disposition: {event.systemDisposition}
                    </p>
                  </div>
                  <Badge variant={event.relationship === "Override" ? "attention" : event.relationship === "Accept" ? "verified" : "outline"}>
                    {event.relationship}
                  </Badge>
                </div>

                <p className="text-sm leading-6">
                  {event.rationale || "No rationale recorded."}
                </p>

                <dl className="grid gap-3 text-xs sm:grid-cols-2 xl:grid-cols-4">
                  <div><dt className="text-muted-foreground">Decision</dt><dd className="mt-1"><Identifier>{event.decisionId}</Identifier></dd></div>
                  <div><dt className="text-muted-foreground">Thesis version</dt><dd className="mt-1"><Identifier>{event.thesisVersionId}</Identifier></dd></div>
                  <div><dt className="text-muted-foreground">Committee</dt><dd className="mt-1"><Identifier>{event.committeeResultId}</Identifier></dd></div>
                  <div><dt className="text-muted-foreground">Readiness gate</dt><dd className="mt-1"><Identifier>{event.readinessGateResultId}</Identifier></dd></div>
                  <div><dt className="text-muted-foreground">Supersedes</dt><dd className="mt-1"><Identifier>{event.supersedesDecisionId}</Identifier></dd></div>
                  <div><dt className="text-muted-foreground">Policy</dt><dd className="mt-1"><Identifier>{event.policyVersion}</Identifier></dd></div>
                  <div><dt className="text-muted-foreground">Idempotency key</dt><dd className="mt-1"><Identifier>{event.idempotencyKey}</Identifier></dd></div>
                  <div><dt className="text-muted-foreground">Created</dt><dd className="mt-1 font-mono text-[11px]">{event.createdAt}</dd></div>
                </dl>

                <div className="grid gap-3 border-t border-border pt-4 lg:grid-cols-2">
                  <div className="rounded-lg bg-muted/40 p-4">
                    <p className="text-xs font-medium">Deep-research command</p>
                    {event.command === null ? (
                      <p className="mt-2 text-xs text-muted-foreground">No command emitted by this event.</p>
                    ) : (
                      <div className="mt-2 grid gap-1">
                        <Identifier>{event.command.commandId}</Identifier>
                        <p className="text-xs">{event.command.type} · {event.command.state}</p>
                        <Identifier>{event.command.policyVersion}</Identifier>
                        <Identifier>{event.command.idempotencyKey}</Identifier>
                      </div>
                    )}
                  </div>
                  <div className="rounded-lg bg-muted/40 p-4">
                    <p className="flex items-center gap-2 text-xs font-medium">
                      <Milestone aria-hidden="true" className="size-4 text-primary" />
                      Portfolio-review handoff marker
                    </p>
                    {event.handoffMarker === null ? (
                      <p className="mt-2 text-xs text-muted-foreground">No handoff marker emitted by this event.</p>
                    ) : (
                      <div className="mt-2 grid gap-1">
                        <Identifier>{event.handoffMarker.markerId}</Identifier>
                        <p className="text-xs">
                          {event.handoffMarker.thesisStatus} · {event.handoffMarker.finalSystemDisposition} · {event.handoffMarker.readinessStatus}
                        </p>
                        <Identifier>{event.handoffMarker.policyVersion}</Identifier>
                        <Identifier>{event.handoffMarker.idempotencyKey}</Identifier>
                      </div>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>
    </section>
  );
}
