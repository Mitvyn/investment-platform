"use client";

import { useEffect, useRef, useTransition } from "react";
import { useRouter } from "next/navigation";

import { resumeMoomooSilently } from "@/app/moomoo-actions";

export function MoomooAutoReconnect({
  active,
  clientId,
}: {
  active: boolean;
  clientId: string | null;
}) {
  const attempted = useRef(false);
  const router = useRouter();
  const [, startTransition] = useTransition();

  useEffect(() => {
    if (!active || !clientId || attempted.current) return;
    attempted.current = true;
    startTransition(async () => {
      await resumeMoomooSilently(clientId);
      router.refresh();
    });
  }, [active, clientId, router]);

  return null;
}
