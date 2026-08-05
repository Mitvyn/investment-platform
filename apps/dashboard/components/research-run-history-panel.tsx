import { ArrowUpRight, History } from "lucide-react";

import type { ResearchRunHistoryPresentation } from "@/lib/research-run-history-workspace";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function ResearchRunHistoryPanel({
  presentation,
}: {
  presentation: ResearchRunHistoryPresentation;
}) {
  if (presentation.kind === "empty") {
    return (
      <Card className="mt-5" aria-labelledby="research-history-heading">
        <CardHeader>
          <p className="font-mono text-[11px] font-medium tracking-[0.14em] text-primary uppercase">
            Finalized research
          </p>
          <CardTitle id="research-history-heading">{presentation.title}</CardTitle>
          <CardDescription>{presentation.description}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <section
      className="mt-5 grid gap-4"
      aria-labelledby="research-history-heading"
    >
      <Card>
        <CardHeader className="gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
          <div>
            <p className="font-mono text-[11px] font-medium tracking-[0.14em] text-primary uppercase">
              Latest finalized Research Run
            </p>
            <CardTitle
              className="mt-2 font-serif text-3xl"
              id="research-history-heading"
            >
              {presentation.latest.finalDisposition}
            </CardTitle>
            <CardDescription className="mt-2">
              Deterministic research disposition. Not trade advice, position
              sizing, or portfolio approval.
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant={presentation.latest.eligibility.variant}>
              {presentation.latest.eligibility.label}
            </Badge>
            <Badge variant={presentation.latest.workflowState.variant}>
              {presentation.latest.workflowState.label}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-5">
          <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">Committee status</dt>
              <dd className="mt-1 text-sm">{presentation.latest.committeeStatus}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Requested disposition</dt>
              <dd className="mt-1 text-sm">{presentation.latest.requestedDisposition}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Evidence cutoff</dt>
              <dd className="mt-1 font-mono text-xs">
                {formatDateTime(presentation.latest.cutoff)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Run created</dt>
              <dd className="mt-1 font-mono text-xs">
                {formatDateTime(presentation.latest.createdAt)}
              </dd>
            </div>
          </dl>
          <Button asChild className="w-fit" size="sm">
            <a href={presentation.latest.auditHref}>
              Open latest audit
              <ArrowUpRight aria-hidden="true" />
            </a>
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <History aria-hidden="true" className="size-5 text-primary" />
          <CardTitle>Research Run history</CardTitle>
          <CardDescription>
            Finalized eligibility snapshots, newest first. Missing dispositions
            remain explicit.
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[52rem] text-left text-sm">
            <caption className="sr-only">
              Finalized Research Run history for selected stable security
            </caption>
            <thead className="border-b border-border text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-3" scope="col">Run</th>
                <th className="px-3 py-3" scope="col">Cutoff</th>
                <th className="px-3 py-3" scope="col">Eligibility</th>
                <th className="px-3 py-3" scope="col">Workflow state</th>
                <th className="px-3 py-3" scope="col">Final disposition</th>
                <th className="px-3 py-3 text-right" scope="col">Audit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {presentation.items.map((item) => (
                <tr key={item.runId}>
                  <th className="px-3 py-4 font-mono text-xs" scope="row">
                    <span className="[overflow-wrap:anywhere]">{item.runId}</span>
                    {item.isLatest ? (
                      <Badge className="ml-2" variant="outline">Latest</Badge>
                    ) : null}
                  </th>
                  <td className="px-3 py-4 font-mono text-xs">
                    {formatDateTime(item.cutoff)}
                  </td>
                  <td className="px-3 py-4">
                    <Badge variant={item.eligibility.variant}>
                      {item.eligibility.label}
                    </Badge>
                  </td>
                  <td className="px-3 py-4">
                    <Badge variant={item.workflowState.variant}>
                      {item.workflowState.label}
                    </Badge>
                  </td>
                  <td className="px-3 py-4">{item.finalDisposition}</td>
                  <td className="px-3 py-4 text-right">
                    <Button asChild size="sm" variant="outline">
                      <a href={item.auditHref}>Open audit</a>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </section>
  );
}
