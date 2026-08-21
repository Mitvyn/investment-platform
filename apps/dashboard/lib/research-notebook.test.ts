import assert from "node:assert/strict";
import test from "node:test";

import {
  addTickerNotebookNote,
  isCanonicalSecurityKnown,
  loadTickerNotebook,
} from "./research-notebook.ts";

const SECURITY_A = "11111111-1111-4111-8111-111111111111";
const SECURITY_B = "22222222-2222-4222-8222-222222222222";

const READY_ENVIRONMENT = {
  IROS_DESKTOP: "1",
  IROS_DESKTOP_CONTROL_ORIGIN: "http://127.0.0.1:4123",
  IROS_DESKTOP_CONTROL_TOKEN: "a".repeat(40),
  IROS_DESKTOP_WORKER_STATE: "ready",
};

function jsonResponse(status: number, payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

test("loadTickerNotebook reports unavailable without a running desktop worker", async () => {
  const result = await loadTickerNotebook(SECURITY_A, {}, async () => {
    throw new Error("must not be called");
  });
  assert.equal(result.state, "unavailable");
  assert.equal(result.notes.length, 0);
});

test("loadTickerNotebook rejects a non-canonical security id before any fetch", async () => {
  const result = await loadTickerNotebook("AAPL", READY_ENVIRONMENT, async () => {
    throw new Error("must not be called");
  });
  assert.equal(result.state, "unavailable");
});

test("loadTickerNotebook only sends the bearer token to the local control origin and scopes by security_id", async () => {
  let capturedUrl: string | null = null;
  let capturedAuth: string | null = null;
  const result = await loadTickerNotebook(
    SECURITY_A,
    READY_ENVIRONMENT,
    async (input, init) => {
      capturedUrl = String(input);
      capturedAuth = (init?.headers as Record<string, string>).Authorization;
      return jsonResponse(200, {
        contract_version: "ticker_notebook_list.v1",
        notes: [
          {
            author_role: "operator",
            body: "Financing runway note",
            created_at: "2026-08-20T00:00:00.000000Z",
            note_id: "33333333-3333-4333-8333-333333333333",
            security_id: SECURITY_A,
          },
        ],
        order: "newest",
      });
    },
  );
  assert.equal(result.state, "ready");
  assert.equal(result.notes.length, 1);
  assert.equal(result.notes[0].securityId, SECURITY_A);
  assert.match(String(capturedUrl), /\/v1\/research\/notebook\?security_id=/);
  assert.match(String(capturedUrl), new RegExp(SECURITY_A));
  assert.equal(capturedAuth, `Bearer ${READY_ENVIRONMENT.IROS_DESKTOP_CONTROL_TOKEN}`);
});

test("loadTickerNotebook fails closed and returns zero notes when the response contains a foreign security_id", async () => {
  const result = await loadTickerNotebook(SECURITY_A, READY_ENVIRONMENT, async () =>
    jsonResponse(200, {
      contract_version: "ticker_notebook_list.v1",
      notes: [
        {
          author_role: "operator",
          body: "wrong security",
          created_at: "2026-08-20T00:00:00.000000Z",
          note_id: "44444444-4444-4444-8444-444444444444",
          security_id: SECURITY_B,
        },
      ],
      order: "newest",
    }),
  );
  assert.equal(result.state, "failed");
  assert.equal(result.notes.length, 0);
});

test("loadTickerNotebook fails closed when only some notes in the response carry a foreign security_id", async () => {
  const result = await loadTickerNotebook(SECURITY_A, READY_ENVIRONMENT, async () =>
    jsonResponse(200, {
      contract_version: "ticker_notebook_list.v1",
      notes: [
        {
          author_role: "operator",
          body: "correct security",
          created_at: "2026-08-20T00:00:00.000000Z",
          note_id: "44444444-4444-4444-8444-444444444444",
          security_id: SECURITY_A,
        },
        {
          author_role: "operator",
          body: "wrong security",
          created_at: "2026-08-20T00:00:01.000000Z",
          note_id: "66666666-6666-4666-8666-666666666666",
          security_id: SECURITY_B,
        },
      ],
      order: "newest",
    }),
  );
  assert.equal(result.state, "failed");
  assert.equal(result.notes.length, 0);
});

test("loadTickerNotebook reports failed state on malformed payload", async () => {
  const result = await loadTickerNotebook(SECURITY_A, READY_ENVIRONMENT, async () =>
    jsonResponse(200, { notes: "not-an-array" }),
  );
  assert.equal(result.state, "failed");
});

test("addTickerNotebookNote rejects blank and oversized bodies before any fetch", async () => {
  await assert.rejects(() =>
    addTickerNotebookNote(SECURITY_A, "   ", READY_ENVIRONMENT, async () => {
      throw new Error("must not be called");
    }),
  );
  await assert.rejects(() =>
    addTickerNotebookNote(
      SECURITY_A,
      "x".repeat(4_001),
      READY_ENVIRONMENT,
      async () => {
        throw new Error("must not be called");
      },
    ),
  );
});

test("addTickerNotebookNote posts trimmed body with canonical security id and bearer token", async () => {
  let capturedBody: unknown = null;
  let capturedAuth: string | null = null;
  const note = await addTickerNotebookNote(
    SECURITY_A,
    "  Watch financing runway.  ",
    READY_ENVIRONMENT,
    async (_input, init) => {
      capturedBody = JSON.parse(String(init?.body));
      capturedAuth = (init?.headers as Record<string, string>).Authorization;
      return jsonResponse(200, {
        author_role: "operator",
        body: "Watch financing runway.",
        contract_version: "ticker_notebook_note.v1",
        created_at: "2026-08-20T00:00:00.000000Z",
        note_id: "55555555-5555-4555-8555-555555555555",
        security_id: SECURITY_A,
      });
    },
  );
  assert.deepEqual(capturedBody, {
    body: "Watch financing runway.",
    security_id: SECURITY_A,
  });
  assert.equal(capturedAuth, `Bearer ${READY_ENVIRONMENT.IROS_DESKTOP_CONTROL_TOKEN}`);
  assert.equal(note.body, "Watch financing runway.");
  assert.equal(note.securityId, SECURITY_A);
});

test("addTickerNotebookNote rejects a response whose security_id differs from the submitted security_id", async () => {
  await assert.rejects(() =>
    addTickerNotebookNote(
      SECURITY_A,
      "Watch financing runway.",
      READY_ENVIRONMENT,
      async () =>
        jsonResponse(200, {
          author_role: "operator",
          body: "Watch financing runway.",
          contract_version: "ticker_notebook_note.v1",
          created_at: "2026-08-20T00:00:00.000000Z",
          note_id: "77777777-7777-4777-8777-777777777777",
          security_id: SECURITY_B,
        }),
    ),
  );
});

test("isCanonicalSecurityKnown only accepts a canonical security id present in the known directory", () => {
  assert.equal(isCanonicalSecurityKnown(SECURITY_A, [SECURITY_A, SECURITY_B]), true);
  assert.equal(isCanonicalSecurityKnown(SECURITY_B, [SECURITY_A]), false);
  assert.equal(isCanonicalSecurityKnown("not-a-uuid", [SECURITY_A]), false);
  assert.equal(isCanonicalSecurityKnown(SECURITY_A, []), false);
});
