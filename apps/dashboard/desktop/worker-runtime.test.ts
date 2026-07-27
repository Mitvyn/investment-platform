import assert from "node:assert/strict";

import {
  launchDesktopWorker,
  resolveDesktopWorkerLaunch,
} from "./worker-runtime.ts";

Deno.test("desktop runtime launches worker and owns clean shutdown", async () => {
  const repositoryRoot = new URL("../../..", import.meta.url);
  const runtime = await launchDesktopWorker({
    args: ["-m", "workers.desktop"],
    command: "python3",
    cwd: repositoryRoot,
    readyTimeoutMs: 1_000,
  });

  assert.deepEqual(runtime.status, {
    contract_version: "desktop_worker_status.v1",
    state: "ready",
    worker_id: "iros-desktop-worker",
  });
  assert.equal(await runtime.stop(), 0);
});

Deno.test("desktop runtime rejects malformed worker readiness", async () => {
  await assert.rejects(
    () =>
      launchDesktopWorker({
        args: ["-c", "print('not-json', flush=True)"],
        command: "python3",
        readyTimeoutMs: 1_000,
      }),
    {
      message: "Desktop worker returned malformed readiness JSON",
    },
  );
});

Deno.test("desktop runtime bounds startup when worker ignores graceful shutdown", async () => {
  const startedAt = performance.now();

  await assert.rejects(
    () =>
      launchDesktopWorker({
        args: [
          "-c",
          "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
        ],
        command: "python3",
        readyTimeoutMs: 25,
      }),
    {
      message: "Desktop worker readiness timed out",
    },
  );

  assert.ok(performance.now() - startedAt < 2_000);
});

Deno.test("desktop runtime resolves packaged worker from macOS app resources", () => {
  assert.deepEqual(
    resolveDesktopWorkerLaunch(
      {},
      "/Applications/IROS.app/Contents/MacOS/laufey_webview",
    ),
    {
      args: [],
      command: "/Applications/IROS.app/Contents/Resources/iros-worker",
      cwd: undefined,
    },
  );
});
