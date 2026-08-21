import assert from "node:assert/strict";
import test from "node:test";

import { importResearchCapture } from "./research-capture-import.ts";

const OPERATOR_ID = "11111111-1111-4111-8111-111111111111";
const SECURITY_ID = "22222222-2222-4222-8222-222222222222";

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

function baseRequest(overrides: Record<string, unknown> = {}) {
  return {
    archivePath: "/tmp/capture.zip",
    asOfCutoff: "2026-05-06T23:59:59Z",
    cik: "0001601830",
    issuerName: "Recursion Pharmaceuticals, Inc.",
    operatorId: OPERATOR_ID,
    primaryListingExchange: "NASDAQ",
    securityId: SECURITY_ID,
    trustedIssuerHosts: ["ir.recursion.com"],
    ...overrides,
  };
}

test("importResearchCapture fails closed without a running desktop worker", async () => {
  await assert.rejects(() =>
    importResearchCapture(baseRequest(), {}, async () => {
      throw new Error("must not be called");
    }),
  );
});

test("importResearchCapture rejects a relative archive path before any fetch", async () => {
  await assert.rejects(() =>
    importResearchCapture(
      baseRequest({ archivePath: "relative/capture.zip" }),
      READY_ENVIRONMENT,
      async () => {
        throw new Error("must not be called");
      },
    ),
  );
});

test("importResearchCapture rejects missing trusted issuer hosts before any fetch", async () => {
  await assert.rejects(() =>
    importResearchCapture(
      baseRequest({ trustedIssuerHosts: ["  "] }),
      READY_ENVIRONMENT,
      async () => {
        throw new Error("must not be called");
      },
    ),
  );
});

test("importResearchCapture posts canonical identity and bearer token to the local control origin only", async () => {
  let capturedUrl: string | null = null;
  let capturedAuth: string | null = null;
  let capturedBody: unknown = null;
  const result = await importResearchCapture(
    baseRequest(),
    READY_ENVIRONMENT,
    async (input, init) => {
      capturedUrl = String(input);
      capturedAuth = (init?.headers as Record<string, string>).Authorization;
      capturedBody = JSON.parse(String(init?.body));
      return jsonResponse(200, {
        accepted_at: "2026-05-07T03:00:00+00:00",
        as_of_cutoff: "2026-05-06T23:59:59+00:00",
        capture_content_hash: "3".repeat(64),
        capture_id: "cf535a4f-b7ff-4aed-9457-8e9d0cbd5535",
        capture_revision: 1,
        contract_version: "primary_source_capture_import_receipt.v1",
        question_type: "biotech_moonshot_catalyst_assessment",
        question_type_version: "biotech_moonshot_catalyst_assessment.v1",
        workflow_config_version: "biotech-moonshot-catalyst-v1",
      });
    },
  );
  assert.equal(capturedUrl, "http://127.0.0.1:4123/v1/research/captures/import");
  assert.equal(capturedAuth, `Bearer ${READY_ENVIRONMENT.IROS_DESKTOP_CONTROL_TOKEN}`);
  const body = capturedBody as Record<string, unknown>;
  assert.equal(body.security_id, SECURITY_ID);
  assert.equal(body.operator_id, OPERATOR_ID);
  assert.deepEqual(body.trusted_issuer_hosts, ["ir.recursion.com"]);
  assert.equal(result.captureId, "cf535a4f-b7ff-4aed-9457-8e9d0cbd5535");
  assert.equal(result.captureRevision, 1);
});

test("importResearchCapture throws on a malformed loopback receipt", async () => {
  await assert.rejects(() =>
    importResearchCapture(baseRequest(), READY_ENVIRONMENT, async () =>
      jsonResponse(200, { ok: true }),
    ),
  );
});

test("importResearchCapture throws when the loopback rejects the request", async () => {
  await assert.rejects(() =>
    importResearchCapture(baseRequest(), READY_ENVIRONMENT, async () =>
      jsonResponse(400, { error: "primary_source_capture_import_invalid" }),
    ),
  );
});
