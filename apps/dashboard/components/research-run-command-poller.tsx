"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { researchRunCommandNavigation } from "@/lib/research-run-command-navigation";
import type { ResearchRunCommandState } from "../../../packages/types/research-run-command";

export function ResearchRunCommandPoller({
  researchRunId,
  state,
}: {
  researchRunId: string | null;
  state: ResearchRunCommandState;
}) {
  const router = useRouter();
  const [pollsCompleted, setPollsCompleted] = useState(0);
  const [elapsedMilliseconds, setElapsedMilliseconds] = useState(0);
  const [startedAt] = useState(() => Date.now());
  const navigation = researchRunCommandNavigation(
    state,
    researchRunId,
    pollsCompleted,
    elapsedMilliseconds,
  );

  useEffect(() => {
    if (navigation.kind === "open_research_run") {
      router.replace(navigation.href);
      return;
    }
    if (navigation.kind !== "refresh") return;
    const timer = window.setTimeout(() => {
      const elapsed = Date.now() - startedAt;
      const nextPollCount = pollsCompleted + 1;
      setElapsedMilliseconds(elapsed);
      setPollsCompleted(nextPollCount);
      if (
        researchRunCommandNavigation(
          state,
          researchRunId,
          nextPollCount,
          elapsed,
        ).kind === "pause"
      ) {
        return;
      }
      router.refresh();
    }, 3_000);
    return () => window.clearTimeout(timer);
  }, [navigation, pollsCompleted, researchRunId, router, startedAt, state]);

  return navigation.kind === "pause" ? (
    <p className="mt-4 text-xs text-warning">
      Automatic refresh paused after two minutes. Reload to check worker status.
    </p>
  ) : null;
}
