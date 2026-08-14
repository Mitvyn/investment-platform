import { dirname } from "node:path";

export type DesktopWindowSize = {
  height: number;
  width: number;
};

type ReadTextFile = (path: string) => Promise<string>;

export type WindowStateStorage = {
  makeDirectory(path: string): Promise<void>;
  rename(from: string, to: string): Promise<void>;
  writeTextFile(path: string, content: string): Promise<void>;
};

export const DEFAULT_DESKTOP_WINDOW_SIZE: DesktopWindowSize = {
  height: 860,
  width: 1280,
};

function isDesktopWindowSize(value: unknown): value is DesktopWindowSize {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<DesktopWindowSize>;
  return Number.isInteger(candidate.width) &&
    Number(candidate.width) >= 800 &&
    Number(candidate.width) <= 5120 &&
    Number.isInteger(candidate.height) &&
    Number(candidate.height) >= 600 &&
    Number(candidate.height) <= 2880;
}

export async function loadWindowSize(
  path: string,
  readTextFile: ReadTextFile = Deno.readTextFile,
): Promise<DesktopWindowSize> {
  try {
    const saved = JSON.parse(await readTextFile(path)) as unknown;
    return isDesktopWindowSize(saved) ? saved : DEFAULT_DESKTOP_WINDOW_SIZE;
  } catch {
    return DEFAULT_DESKTOP_WINDOW_SIZE;
  }
}

export async function persistWindowSize(
  path: string,
  size: DesktopWindowSize,
  storage: WindowStateStorage = {
    makeDirectory: (directory) => Deno.mkdir(directory, { recursive: true }),
    rename: Deno.rename,
    writeTextFile: Deno.writeTextFile,
  },
): Promise<void> {
  if (!isDesktopWindowSize(size)) {
    throw new TypeError("desktop window size is invalid");
  }
  const temporaryPath = `${path}.tmp`;
  await storage.makeDirectory(dirname(path));
  await storage.writeTextFile(
    temporaryPath,
    `${JSON.stringify({ height: size.height, width: size.width })}\n`,
  );
  await storage.rename(temporaryPath, path);
}
