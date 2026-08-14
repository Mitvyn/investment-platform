"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function MoomooClientIdPicker({
  savedClientIds,
}: {
  savedClientIds: readonly string[];
}) {
  const [usesNewClientId, setUsesNewClientId] = useState(
    savedClientIds.length === 0,
  );

  if (usesNewClientId) {
    return (
      <div className="flex gap-2">
        <Input
          autoComplete="off"
          id="moomooClientId"
          name="clientId"
          placeholder="OAuth client UUID"
          required
        />
        {savedClientIds.length > 0 ? (
          <Button
            onClick={() => setUsesNewClientId(false)}
            type="button"
            variant="outline"
          >
            Saved IDs
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="relative">
      <select
        className="flex h-11 w-full appearance-none rounded-md border border-input bg-background/70 px-3 py-2 pr-10 font-mono text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/35"
        defaultValue={savedClientIds[0]}
        id="moomooClientId"
        name="clientId"
        onChange={(event) => {
          if (event.currentTarget.value === "__new__") {
            setUsesNewClientId(true);
          }
        }}
        required
      >
        {savedClientIds.map((clientId) => (
          <option key={clientId} value={clientId}>
            {clientId}
          </option>
        ))}
        <option value="__new__">Use another client ID…</option>
      </select>
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
      />
    </div>
  );
}
