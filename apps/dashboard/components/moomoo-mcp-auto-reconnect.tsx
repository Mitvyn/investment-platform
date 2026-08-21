"use client";

import { useEffect, useRef, useTransition } from "react";
import { useRouter } from "next/navigation";

import { resumeMoomooMcpSilently } from "@/app/moomoo-actions";

/**
 * Silent startup resume for the core Moomoo (MCP) connection.
 *
 * Runs once per page load whenever the MCP connection is not already ready
 * and auto-resume has not been intentionally disabled (see `active`), with
 * no browser popup and no manual discovery step. Independent of the
 * optional OpenAPI streaming auto-reconnect component: it never reads that
 * connection's state and never blocks on it.
 */
export function MoomooMcpAutoReconnect({ active }: { active: boolean }) {
  const attempted = useRef(false);
  const router = useRouter();
  const [, startTransition] = useTransition();

  useEffect(() => {
    if (!active || attempted.current) return;
    attempted.current = true;
    startTransition(async () => {
      await resumeMoomooMcpSilently();
      router.refresh();
    });
  }, [active, router]);

  return null;
}
