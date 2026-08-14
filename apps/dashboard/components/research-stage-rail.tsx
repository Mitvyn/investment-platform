import Link from "next/link";
import { ArrowUpRight, Lock } from "lucide-react";

import type { ResearchStage, ResearchStageState } from "@/lib/dashboard-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * The stage rail for one Research Run. Stages are steps inside a single
 * feature, not global navigation, so every stage stays visible and reachable
 * even when it has no artifact — a hidden stage would leave the operator
 * unable to tell how far the run got.
 */
export function ResearchStageRail({
  activeStage,
  hrefForStage,
  stages,
}: {
  activeStage: ResearchStage;
  hrefForStage: (stage: ResearchStage) => string;
  stages: ResearchStageState[];
}) {
  return (
    <nav aria-label="Research Run stages" className="mt-5">
      <ol className="flex flex-wrap items-center gap-1">
        {stages.map((stage, index) => {
          const current = stage.id === activeStage;
          return (
            <li className="flex items-center gap-1" key={stage.id}>
              {index > 0 ? (
                <span aria-hidden="true" className="text-muted-foreground/40">
                  ·
                </span>
              ) : null}
              <Link
                aria-current={current ? "page" : undefined}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  current
                    ? "bg-primary text-primary-foreground"
                    : stage.available
                      ? "text-foreground hover:bg-muted"
                      : "text-muted-foreground hover:bg-muted/60"
                }`}
                href={hrefForStage(stage.id)}
              >
                <span
                  aria-hidden="true"
                  className="font-mono text-[10px] opacity-60"
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                {stage.label}
                {stage.available ? null : (
                  <>
                    <Lock aria-hidden="true" className="size-3" />
                    <span className="sr-only">(no artifact yet)</span>
                  </>
                )}
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/**
 * Shown in place of a stage body when the stage has no persisted artifact.
 * States the cause and the single next action rather than rendering blank.
 */
export function ResearchStageUnavailable({ stage }: { stage: ResearchStageState }) {
  return (
    <Card className="mt-5 border-dashed">
      <CardHeader>
        <p className="font-mono text-[11px] font-medium tracking-[0.14em] text-muted-foreground uppercase">
          {stage.label} unavailable
        </p>
        <CardTitle className="mt-2 text-lg">{stage.blockedReason}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">{stage.nextStep}</p>
      </CardContent>
    </Card>
  );
}

/** Link into the run route for stages whose artifact is persisted there. */
export function ResearchStageRunLink({
  label,
  runHref,
}: {
  label: string;
  runHref: string;
}) {
  return (
    <Card className="mt-5">
      <CardHeader>
        <p className="font-mono text-[11px] font-medium tracking-[0.14em] text-primary uppercase">
          {label}
        </p>
        <CardTitle className="mt-2 text-lg">
          Produced by the latest finalized Research Run
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Link
          className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
          href={runHref}
        >
          Open the run record
          <ArrowUpRight aria-hidden="true" className="size-4" />
        </Link>
        <p className="mt-3 text-xs text-muted-foreground">
          Immutable run artifacts stay on their own auditable record.
        </p>
      </CardContent>
    </Card>
  );
}
