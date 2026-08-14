import assert from "node:assert/strict";

import { loadWindowSize, persistWindowSize } from "./window-state.ts";

Deno.test("desktop window restores the last valid size", async () => {
  const size = await loadWindowSize(
    "/unused/window-state.json",
    async () => JSON.stringify({ height: 910, width: 1420 }),
  );

  assert.deepEqual(size, { height: 910, width: 1420 });
});

Deno.test("desktop window uses sidebar-friendly defaults when state is unreadable", async () => {
  const size = await loadWindowSize(
    "/unused/window-state.json",
    async () => {
      throw new Deno.errors.NotFound("missing");
    },
  );

  assert.deepEqual(size, { height: 860, width: 1280 });
});

Deno.test("desktop window rejects malformed or unsafe saved dimensions", async () => {
  const size = await loadWindowSize(
    "/unused/window-state.json",
    async () => JSON.stringify({ height: "910", width: 0 }),
  );

  assert.deepEqual(size, { height: 860, width: 1280 });
});

Deno.test("desktop window persists resized dimensions atomically", async () => {
  const calls: string[] = [];

  await persistWindowSize(
    "/Users/test/Library/Application Support/Investment Research OS/window-state.json",
    { height: 910, width: 1420 },
    {
      makeDirectory: async (path) => {
        calls.push(`mkdir:${path}`);
      },
      rename: async (from, to) => {
        calls.push(`rename:${from}:${to}`);
      },
      writeTextFile: async (path, content) => {
        calls.push(`write:${path}:${content}`);
      },
    },
  );

  assert.deepEqual(calls, [
    "mkdir:/Users/test/Library/Application Support/Investment Research OS",
    'write:/Users/test/Library/Application Support/Investment Research OS/window-state.json.tmp:{"height":910,"width":1420}\n',
    "rename:/Users/test/Library/Application Support/Investment Research OS/window-state.json.tmp:/Users/test/Library/Application Support/Investment Research OS/window-state.json",
  ]);
});
