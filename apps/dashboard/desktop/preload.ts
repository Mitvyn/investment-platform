import { join } from "node:path";

import {
  launchDesktopWorker,
  resolveDesktopWorkerLaunch,
} from "./worker-runtime.ts";
import { loadWindowSize, persistWindowSize } from "./window-state.ts";

type DesktopBrowserWindow = {
  addEventListener(type: "resize", listener: () => void): void;
  getSize(): [number, number];
};

type DesktopBrowserWindowConstructor = new (options: {
  height: number;
  title: string;
  width: number;
}) => DesktopBrowserWindow;

const BrowserWindow = Reflect.get(Deno, "BrowserWindow") as
  | DesktopBrowserWindowConstructor
  | undefined;
if (!BrowserWindow) {
  throw new Error("Deno Desktop BrowserWindow API is unavailable");
}

const homeDirectory = Deno.env.get("HOME") ?? Deno.cwd();
const windowStatePath = join(
  homeDirectory,
  "Library",
  "Application Support",
  "Investment Research OS",
  "window-state.json",
);
const initialWindowSize = await loadWindowSize(windowStatePath);
const appWindow = new BrowserWindow({
  height: initialWindowSize.height,
  title: "Investment Research OS",
  width: initialWindowSize.width,
});
let resizeSaveTimer: ReturnType<typeof setTimeout> | undefined;

appWindow.addEventListener("resize", () => {
  if (resizeSaveTimer !== undefined) clearTimeout(resizeSaveTimer);
  resizeSaveTimer = setTimeout(() => {
    const [width, height] = appWindow.getSize();
    void persistWindowSize(windowStatePath, { height, width }).catch(() => {
      // Window-state persistence must never prevent app use or worker cleanup.
    });
  }, 250);
});

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
  Deno.env.set("IROS_DESKTOP_CONTROL_ORIGIN", runtime.status.control_origin);
  Deno.env.set("IROS_DESKTOP_CONTROL_TOKEN", runtime.status.control_token);
  globalThis.addEventListener("unload", () => {
    if (resizeSaveTimer !== undefined) clearTimeout(resizeSaveTimer);
    void runtime.stop();
  });
} catch {
  Deno.env.set("IROS_DESKTOP_WORKER_STATE", "failed");
}
