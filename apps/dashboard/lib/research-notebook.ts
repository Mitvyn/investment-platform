type DesktopEnvironment = Record<string, string | undefined>;
type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export type TickerNotebookNote = {
  authorRole: "operator";
  body: string;
  createdAt: string;
  noteId: string;
  securityId: string;
};

export type TickerNotebookList = {
  detail: string;
  notes: TickerNotebookNote[];
  state: "failed" | "ready" | "unavailable";
};

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CONTROL_ORIGIN_PATTERN = /^http:\/\/127\.0\.0\.1:\d+$/;
const MAX_NOTES_RETURNED = 100;
const MAX_NOTE_BODY_CHARS = 4_000;

function controlContract(environment: DesktopEnvironment) {
  const origin = environment.IROS_DESKTOP_CONTROL_ORIGIN ?? "";
  const token = environment.IROS_DESKTOP_CONTROL_TOKEN ?? "";
  if (
    environment.IROS_DESKTOP !== "1" ||
    environment.IROS_DESKTOP_WORKER_STATE !== "ready" ||
    !CONTROL_ORIGIN_PATTERN.test(origin) ||
    token.length < 32
  ) {
    return null;
  }
  return { origin, token };
}

function isTickerNotebookNote(value: unknown): value is {
  author_role: "operator";
  body: string;
  created_at: string;
  note_id: string;
  security_id: string;
} {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate.author_role === "operator" &&
    typeof candidate.body === "string" &&
    candidate.body.length > 0 &&
    candidate.body.length <= MAX_NOTE_BODY_CHARS &&
    typeof candidate.created_at === "string" &&
    typeof candidate.note_id === "string" &&
    typeof candidate.security_id === "string" &&
    UUID_PATTERN.test(candidate.security_id)
  );
}

function isTickerNotebookListPayload(value: unknown): value is {
  contract_version: "ticker_notebook_list.v1";
  notes: unknown[];
  order: "newest" | "oldest";
} {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate.contract_version === "ticker_notebook_list.v1" &&
    Array.isArray(candidate.notes) &&
    candidate.notes.length <= MAX_NOTES_RETURNED &&
    candidate.notes.every(isTickerNotebookNote) &&
    (candidate.order === "newest" || candidate.order === "oldest")
  );
}

function presentNote(note: {
  author_role: "operator";
  body: string;
  created_at: string;
  note_id: string;
  security_id: string;
}): TickerNotebookNote {
  return {
    authorRole: note.author_role,
    body: note.body,
    createdAt: note.created_at,
    noteId: note.note_id,
    securityId: note.security_id,
  };
}

export async function loadTickerNotebook(
  securityId: string,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<TickerNotebookList> {
  if (!UUID_PATTERN.test(securityId)) {
    return {
      detail: "Select a security before opening its Research Notebook",
      notes: [],
      state: "unavailable",
    };
  }
  const contract = controlContract(environment);
  if (!contract) {
    return {
      detail: "Open desktop app to read this security's Research Notebook",
      notes: [],
      state: "unavailable",
    };
  }
  try {
    const url = new URL("/v1/research/notebook", contract.origin);
    url.searchParams.set("security_id", securityId);
    const response = await fetcher(url, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${contract.token}` },
      signal: AbortSignal.timeout(3_000),
    });
    const payload: unknown = await response.json();
    if (!response.ok || !isTickerNotebookListPayload(payload)) {
      throw new Error("ticker notebook list request failed");
    }
    const rawNotes = payload.notes as Parameters<typeof presentNote>[0][];
    if (rawNotes.some((note) => note.security_id !== securityId)) {
      throw new Error("ticker notebook list request returned a foreign security_id");
    }
    const notes = rawNotes.map(presentNote);
    return {
      detail:
        notes.length === 0
          ? "No notes recorded yet for this security"
          : `${notes.length} note${notes.length === 1 ? "" : "s"} recorded locally`,
      notes,
      state: "ready",
    };
  } catch {
    return {
      detail: "Research Notebook is unavailable. Retry after checking the desktop app.",
      notes: [],
      state: "failed",
    };
  }
}

export async function addTickerNotebookNote(
  securityId: string,
  body: string,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<TickerNotebookNote> {
  if (!UUID_PATTERN.test(securityId)) {
    throw new TypeError("ticker notebook security id is invalid");
  }
  const trimmed = body.trim();
  if (!trimmed || trimmed.length > MAX_NOTE_BODY_CHARS) {
    throw new TypeError("ticker notebook note body is invalid");
  }
  const contract = controlContract(environment);
  if (!contract) {
    throw new Error("Research Notebook is unavailable");
  }
  const response = await fetcher(`${contract.origin}/v1/research/notebook`, {
    body: JSON.stringify({ body: trimmed, security_id: securityId }),
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${contract.token}`,
      "Content-Type": "application/json",
    },
    method: "POST",
    signal: AbortSignal.timeout(3_000),
  });
  const payload: unknown = await response.json();
  if (
    !response.ok ||
    !isTickerNotebookNote(payload) ||
    payload.security_id !== securityId
  ) {
    throw new Error("ticker notebook note request failed");
  }
  return presentNote(payload);
}

export function isCanonicalSecurityKnown(
  securityId: string,
  knownSecurityIds: readonly string[],
): boolean {
  return UUID_PATTERN.test(securityId) && knownSecurityIds.includes(securityId);
}
