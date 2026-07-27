import assert from "node:assert/strict";
import test from "node:test";

import { readDesktopRuntimeStatus } from "./desktop-runtime.ts";

test("desktop runtime reports packaged worker readiness", () => {
  assert.deepEqual(
    readDesktopRuntimeStatus({
      IROS_DESKTOP: "1",
      IROS_DESKTOP_WORKER_STATE: "ready",
    }),
    {
      detail: "Worker shell passed startup; job routing pending IRO-047",
      state: "ready",
    },
  );
});
