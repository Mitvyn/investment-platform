import assert from "node:assert/strict";
import test from "node:test";

import {
  buildResearchRequestFromAcceptedCapture,
  loadAcceptedResearchCaptures,
  parseAcceptedResearchCaptureSelection,
  resolveAcceptedResearchCapture,
} from "./research-desktop.ts";
import type { AcceptedResearchCapture } from "./research-desktop.ts";

const environment = {
  IROS_DESKTOP: "1",
  IROS_DESKTOP_CONTROL_ORIGIN: "http://127.0.0.1:61555",
  IROS_DESKTOP_CONTROL_TOKEN: "x".repeat(43),
  IROS_DESKTOP_WORKER_STATE: "ready",
};
const request = {
  operatorId: "027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
  securityId: "22222222-2222-4222-8222-222222222222",
} as const;
const captures: AcceptedResearchCapture[] = [
  {
    capture_id: "44444444-4444-4444-8444-444444444444",
    capture_revision: 1,
    capture_content_hash: "a".repeat(64),
    as_of_cutoff: "2026-05-06T23:59:00+00:00",
    question_type: "biotech_moonshot_catalyst_personal_research_assessment",
    question_type_version:
      "biotech_moonshot_catalyst_personal_research_assessment.v1",
    workflow_config_version:
      "biotech-moonshot-catalyst-personal-research-v1",
    accepted_at: "2026-05-07T02:00:00+00:00",
  },
  {
    capture_id: "44444444-4444-4444-8444-444444444444",
    capture_revision: 2,
    capture_content_hash: "b".repeat(64),
    as_of_cutoff: "2026-05-01T23:59:00+00:00",
    question_type: "biotech_moonshot_catalyst_assessment",
    question_type_version: "biotech_moonshot_catalyst_assessment.v1",
    workflow_config_version: "biotech-moonshot-catalyst-v1",
    accepted_at: "2026-05-08T02:00:00+00:00",
  },
];

test("desktop lists bounded accepted captures for authenticated operator and security", async () => {
  const calls: Array<[string, RequestInit]> = [];
  const result = await loadAcceptedResearchCaptures(
    request,
    environment,
    async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return Response.json({
        contract_version: "accepted_research_capture_list.v1",
        capture_count: 2,
        captures,
      });
    },
  );

  assert.deepEqual(result, {
    captures,
    detail: "2 accepted captures available",
    state: "ready",
  });
  const url = new URL(calls[0][0]);
  assert.equal(url.origin, "http://127.0.0.1:61555");
  assert.equal(url.pathname, "/v1/research/captures");
  assert.deepEqual(
    Object.fromEntries(url.searchParams.entries()),
    {
      operator_id: request.operatorId,
      security_id: request.securityId,
    },
  );
  assert.equal(
    (calls[0][1].headers as Record<string, string>).Authorization,
    `Bearer ${"x".repeat(43)}`,
  );
  assert.equal(calls[0][1].cache, "no-store");
});

test("capture listing fails closed without desktop or with invalid wire data", async () => {
  let called = false;
  const unavailable = await loadAcceptedResearchCaptures(
    request,
    {},
    async () => {
      called = true;
      throw new Error("must not fetch");
    },
  );
  assert.equal(called, false);
  assert.deepEqual(unavailable, {
    captures: [],
    detail: "Open desktop app to prepare and select accepted evidence",
    state: "unavailable",
  });

  const malformed = await loadAcceptedResearchCaptures(
    request,
    environment,
    async () =>
      Response.json({
        contract_version: "accepted_research_capture_list.v1",
        capture_count: 1,
        captures: [{ ...captures[0], capture_revision: 0 }],
      }),
  );
  assert.deepEqual(malformed, {
    captures: [],
    detail: "Accepted capture list unavailable",
    state: "failed",
  });
});

test("server exact-resolves selected triple and never substitutes another revision", async () => {
  const selected = captures[0];
  const fetcher = async () =>
    Response.json({
      contract_version: "accepted_research_capture_list.v1",
      capture_count: 2,
      captures,
    });

  assert.deepEqual(
    await resolveAcceptedResearchCapture(
      { ...request, selectedCapture: selected },
      environment,
      fetcher,
    ),
    selected,
  );
  await assert.rejects(
    resolveAcceptedResearchCapture(
      {
        ...request,
        selectedCapture: { ...selected, capture_content_hash: "c".repeat(64) },
      },
      environment,
      fetcher,
    ),
    /selected accepted capture is unavailable/,
  );
});

test("capture select value carries one exact non-editable identity", () => {
  const selection = `${captures[0].capture_id}:${captures[0].capture_revision}:${captures[0].capture_content_hash}`;
  assert.deepEqual(parseAcceptedResearchCaptureSelection(selection), {
    capture_id: captures[0].capture_id,
    capture_revision: captures[0].capture_revision,
    capture_content_hash: captures[0].capture_content_hash,
  });
  assert.throws(
    () => parseAcceptedResearchCaptureSelection("latest"),
    /invalid accepted capture selection/,
  );
});

test("selected receipt, not editable form state, supplies Research Run contract and cutoff", () => {
  assert.deepEqual(
    buildResearchRequestFromAcceptedCapture(
      captures[0],
      request.securityId,
      "  Focus on runway.  ",
    ),
    {
      question_type:
        "biotech_moonshot_catalyst_personal_research_assessment",
      security_id: request.securityId,
      as_of_cutoff: "2026-05-06T23:59:00+00:00",
      workflow_config_version:
        "biotech-moonshot-catalyst-personal-research-v1",
      operator_focus: "  Focus on runway.  ",
    },
  );
});
