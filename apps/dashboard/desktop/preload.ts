import {
  launchDesktopWorker,
  resolveDesktopWorkerLaunch,
} from "./worker-runtime.ts";

Deno.env.set("IROS_DESKTOP", "1");
Deno.env.set("IROS_DESKTOP_WORKER_STATE", "starting");

const launch = resolveDesktopWorkerLaunch(
  {
    IROS_DESKTOP_WORKER_CWD: Deno.env.get("IROS_DESKTOP_WORKER_CWD"),
    IROS_DESKTOP_WORKER_PATH: Deno.env.get("IROS_DESKTOP_WORKER_PATH"),
    IROS_DESKTOP_WORKER_PYTHON: Deno.env.get("IROS_DESKTOP_WORKER_PYTHON"),
  },
  Deno.execPath(),
);

try {
  const runtime = await launchDesktopWorker({
    ...launch,
    parentPid: Deno.pid,
    readyTimeoutMs: 30_000,
  });
  Deno.env.set("IROS_DESKTOP_WORKER_STATE", "ready");
  globalThis.addEventListener("unload", () => {
    void runtime.stop();
  });
} catch {
  Deno.env.set("IROS_DESKTOP_WORKER_STATE", "failed");
}
