"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { researchRunCommandNavigation } from "@/lib/research-run-command-navigation";
import type { ResearchRunCommandState } from "../../../packages/types/research-run-command";

export function ResearchRunCommandPoller({
  contractVersion,
  researchRunId,
  state,
}: {
  contractVersion:
    | "research_run_command_receipt.v1"
    | "research_run_command_receipt.v2";
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
    contractVersion,
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
          contractVersion,
        ).kind === "pause"
      ) {
        return;
      }
      router.refresh();
    }, 3_000);
    return () => window.clearTimeout(timer);
  }, [
    contractVersion,
    navigation,
    pollsCompleted,
    researchRunId,
    router,
    startedAt,
    state,
  ]);

  return navigation.kind === "pause" ? (
    <p className="mt-4 text-xs text-warning">
      Automatic refresh paused after two minutes. Reload to check worker status.
    </p>
  ) : null;
}
