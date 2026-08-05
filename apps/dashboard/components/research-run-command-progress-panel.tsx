import { CircleCheck, Clock3, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { ResearchRunCommandProgressPresentation } from "@/lib/research-run-command-progress-workspace";

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function stateDescription(
  presentation: ResearchRunCommandProgressPresentation,
) {
  if (presentation.state === "blocked") {
    return "Preflight blocked. No worker attempt or workflow stage started.";
  }
  if (presentation.state === "queued") {
    return presentation.attempt === "No attempt"
      ? "Queued and waiting for first worker claim."
      : "Retry queued after a retryable worker attempt.";
  }
  if (presentation.state === "running") {
    return "Worker owns an active stage under a bounded lease.";
  }
  if (presentation.state === "completed") {
    return "Every workflow stage checkpoint completed in canonical order.";
  }
  return "Worker stopped after a terminal command failure.";
}

export function ResearchRunCommandProgressPanel({
  presentation,
}: {
  presentation: ResearchRunCommandProgressPresentation;
}) {
  return (
    <Card aria-labelledby="research-command-progress-heading">
      <CardHeader className="gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
        <div className="min-w-0">
          <p className="font-mono text-[11px] font-medium tracking-[0.14em] text-primary uppercase">
            Research command
          </p>
          <CardTitle
            className="mt-2"
            id="research-command-progress-heading"
          >
            Workflow progress
          </CardTitle>
          <CardDescription className="mt-2">
            {stateDescription(presentation)}
          </CardDescription>
        </div>
        <Badge variant={presentation.status.variant}>
          {presentation.status.label}
        </Badge>
      </CardHeader>

      <CardContent className="grid gap-6">
        <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div>
            <dt className="text-xs text-muted-foreground">Attempt</dt>
            <dd className="mt-1 text-sm">{presentation.attempt}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Active stage</dt>
            <dd className="mt-1 text-sm">{presentation.activeStage}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Lease state</dt>
            <dd className="mt-1">
              <Badge variant={presentation.lease.variant}>
                {presentation.lease.label}
              </Badge>
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Lease expiry</dt>
            <dd className="mt-1 font-mono text-xs">
              {presentation.lease.expiresAt === null
                ? "Not applicable"
                : formatDateTime(presentation.lease.expiresAt)}
            </dd>
          </div>
        </dl>

        <Separator />

        <section aria-labelledby="completed-checkpoints-heading">
          <div className="flex items-center gap-2">
            <CircleCheck aria-hidden="true" className="size-4 text-evidence" />
            <h3
              className="text-sm font-medium"
              id="completed-checkpoints-heading"
            >
              Completed checkpoints
            </h3>
          </div>
          {presentation.completedStages.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">
              No stage checkpoint persisted.
            </p>
          ) : (
            <ol className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {presentation.completedStages.map((checkpoint) => (
                <li
                  className="flex items-center gap-3 rounded-md border border-border bg-muted/35 px-3 py-2"
                  key={checkpoint.stage}
                >
                  <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-evidence-muted font-mono text-[10px] text-evidence-muted-foreground">
                    {checkpoint.ordinal}
                  </span>
                  <span className="text-sm">{checkpoint.label}</span>
                </li>
              ))}
            </ol>
          )}
        </section>

        {presentation.failure === null ? null : (
          <>
            <Separator />
            <section
              className="rounded-md border border-challenge/35 bg-challenge-muted p-4"
              aria-labelledby="terminal-failure-heading"
            >
              <div className="flex items-center gap-2 text-challenge-muted-foreground">
                <ShieldAlert aria-hidden="true" className="size-4" />
                <h3 className="text-sm font-medium" id="terminal-failure-heading">
                  Terminal failure
                </h3>
              </div>
              <dl className="mt-4 grid gap-4 sm:grid-cols-3">
                <div>
                  <dt className="text-xs text-challenge-muted-foreground">
                    Failed stage
                  </dt>
                  <dd className="mt-1 text-sm">{presentation.failure.stage}</dd>
                </div>
                <div>
                  <dt className="text-xs text-challenge-muted-foreground">
                    Error code
                  </dt>
                  <dd className="mt-1 font-mono text-xs [overflow-wrap:anywhere]">
                    {presentation.failure.errorCode}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-challenge-muted-foreground">
                    Retryable
                  </dt>
                  <dd className="mt-1 text-sm">
                    {presentation.failure.retryable ? "Yes" : "No"}
                  </dd>
                </div>
              </dl>
            </section>
          </>
        )}

        <div className="flex min-w-0 items-center gap-2 border-t border-border pt-4 text-xs text-muted-foreground">
          <Clock3 aria-hidden="true" className="size-4 shrink-0" />
          <span>
            Updated {formatDateTime(presentation.updatedAt)}
          </span>
          <span className="min-w-0 truncate font-mono">
            {presentation.commandId}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
