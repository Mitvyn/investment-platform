export type DesktopWorkerStatus = {
  contract_version: "desktop_worker_status.v1";
  control_origin: string;
  control_token: string;
  state: "ready";
  worker_id: "iros-desktop-worker";
};

export type DesktopWorkerRuntime = {
  status: DesktopWorkerStatus;
  stop(): Promise<number>;
};

type LaunchDesktopWorkerOptions = {
  args?: string[];
  command: string;
  cwd?: string | URL;
  parentPid?: number;
  readyTimeoutMs: number;
};

type DesktopWorkerLaunch = {
  args: string[];
  command: string;
  cwd: string | undefined;
};

export function resolveDesktopWorkerLaunch(
  environment: Record<string, string | undefined>,
  executablePath: string,
): DesktopWorkerLaunch {
  const python = environment.IROS_DESKTOP_WORKER_PYTHON;
  if (python) {
    return {
      args: ["-m", "workers.desktop"],
      command: python,
      cwd: environment.IROS_DESKTOP_WORKER_CWD,
    };
  }
  const workerPath = environment.IROS_DESKTOP_WORKER_PATH ??
    join(dirname(dirname(executablePath)), "Resources", "iros-worker");
  return {
    args: [],
    command: workerPath,
    cwd: undefined,
  };
}

function parseReadyStatus(line: string): DesktopWorkerStatus {
  let value: Partial<DesktopWorkerStatus>;
  try {
    value = JSON.parse(line) as Partial<DesktopWorkerStatus>;
  } catch {
    throw new Error("Desktop worker returned malformed readiness JSON");
  }
  if (
    value.contract_version !== "desktop_worker_status.v1" ||
    typeof value.control_origin !== "string" ||
    !/^http:\/\/127\.0\.0\.1:\d+$/.test(value.control_origin) ||
    typeof value.control_token !== "string" ||
    value.control_token.length < 32 ||
    value.state !== "ready" ||
    value.worker_id !== "iros-desktop-worker"
  ) {
    throw new Error("Desktop worker returned an invalid readiness message");
  }
  return value as DesktopWorkerStatus;
}

async function readLine(
  stream: ReadableStream<Uint8Array>,
  timeoutMs: number,
): Promise<string> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let timeout: ReturnType<typeof setTimeout> | undefined;

  try {
    return await Promise.race([
      (async () => {
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            throw new Error("Desktop worker exited before readiness");
          }
          buffer += decoder.decode(value, { stream: true });
          const newline = buffer.indexOf("\n");
          if (newline >= 0) {
            return buffer.slice(0, newline);
          }
        }
      })(),
      new Promise<never>((_resolve, reject) => {
        timeout = setTimeout(
          () => reject(new Error("Desktop worker readiness timed out")),
          timeoutMs,
        );
      }),
    ]);
  } finally {
    if (timeout !== undefined) {
      clearTimeout(timeout);
    }
    reader.releaseLock();
  }
}

export async function launchDesktopWorker(
  options: LaunchDesktopWorkerOptions,
): Promise<DesktopWorkerRuntime> {
  const process = new Deno.Command(options.command, {
    args: options.args ?? [],
    cwd: options.cwd,
    env: options.parentPid === undefined
      ? undefined
      : { IROS_DESKTOP_PARENT_PID: String(options.parentPid) },
    stderr: "null",
    stdout: "piped",
  }).spawn();

  try {
    const status = parseReadyStatus(
      await readLine(process.stdout, options.readyTimeoutMs),
    );
    await process.stdout.cancel();
    process.unref();
    let stopped: Promise<Deno.CommandStatus> | undefined;

    return {
      status,
      async stop() {
        if (!stopped) {
          process.ref();
          process.kill("SIGTERM");
          stopped = process.status;
        }
        return (await stopped).code;
      },
    };
  } catch (error) {
    try {
      process.kill("SIGKILL");
    } catch {
      // The child may have exited between emitting malformed output and cleanup.
    }
    await process.status;
    throw error;
  }
}
import { dirname, join } from "node:path";
