"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { workflowJobNavigation } from "@/lib/workflow-job-navigation";

export function WorkflowJobPoller({
  securityId,
  state,
}: {
  securityId: string | null;
  state: "queued" | "running" | "completed" | "failed";
}) {
  const router = useRouter();
  const [pollsCompleted, setPollsCompleted] = useState(0);
  const [elapsedMilliseconds, setElapsedMilliseconds] = useState(0);
  const [startedAt] = useState(() => Date.now());
  const navigation = workflowJobNavigation(
    state,
    securityId,
    pollsCompleted,
    elapsedMilliseconds,
  );

  useEffect(() => {
    if (navigation.kind === "open_security") {
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
        workflowJobNavigation(
          state,
          securityId,
          nextPollCount,
          elapsed,
        ).kind === "pause"
      ) {
        return;
      }
      router.refresh();
    }, 3_000);
    return () => window.clearTimeout(timer);
  }, [navigation, pollsCompleted, router, securityId, startedAt, state]);

  return navigation.kind === "pause" ? (
    <p className="text-xs text-warning">
      Automatic refresh paused after two minutes. Reload to check worker status.
    </p>
  ) : null;
}
