"use client";

import { useEffect, useRef, useTransition } from "react";
import { useRouter } from "next/navigation";

import {
  resumeMoomooMcpSilently,
  resumeMoomooSilently,
} from "@/app/moomoo-actions";

/**
 * Silent startup resume for the core Moomoo (MCP) connection.
 *
 * Runs once per page load. Core MCP resumes first; optional OpenAPI streaming
 * resumes second. Preferences and outcomes remain independent, while ordered
 * execution prevents concurrent macOS Keychain reads during startup.
 */
export function MoomooConnectionAutoReconnect({
  mcpActive,
  openApiActive,
  openApiClientId,
}: {
  mcpActive: boolean;
  openApiActive: boolean;
  openApiClientId: string | null;
}) {
  const attempted = useRef(false);
  const router = useRouter();
  const [, startTransition] = useTransition();

  useEffect(() => {
    if (
      attempted.current ||
      (!mcpActive && (!openApiActive || !openApiClientId))
    ) return;
    attempted.current = true;
    startTransition(async () => {
      if (mcpActive) await resumeMoomooMcpSilently();
      if (openApiActive && openApiClientId) {
        await resumeMoomooSilently(openApiClientId);
      }
      router.refresh();
    });
  }, [mcpActive, openApiActive, openApiClientId, router]);

  return null;
}
