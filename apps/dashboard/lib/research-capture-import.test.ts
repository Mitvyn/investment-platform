import assert from "node:assert/strict";
import test from "node:test";

import {
  importResearchCapture,
  importResearchCaptureUpload,
} from "./research-capture-import.ts";

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

test("importResearchCaptureUpload sends archive bytes and server-owned identity to loopback", async () => {
  const archive = new Blob([new Uint8Array([80, 75, 3, 4])], {
    type: "application/zip",
  });
  let capturedUrl = "";
  let capturedHeaders: HeadersInit | undefined;
  let capturedBody: unknown;
  const result = await importResearchCaptureUpload(
    {
      archive,
      cik: "0001601830",
      confirmEmbeddedIssuerHosts: true,
      issuerName: "Recursion Pharmaceuticals, Inc.",
      operatorId: OPERATOR_ID,
      primaryListingExchange: "NASDAQ",
      securityId: SECURITY_ID,
    },
    READY_ENVIRONMENT,
    async (input, init) => {
      capturedUrl = String(input);
      capturedHeaders = init?.headers;
      capturedBody = init?.body;
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
  assert.equal(capturedUrl, "http://127.0.0.1:4123/v1/research/captures/upload");
  const headers = new Headers(capturedHeaders);
  assert.equal(headers.get("Authorization"), `Bearer ${READY_ENVIRONMENT.IROS_DESKTOP_CONTROL_TOKEN}`);
  assert.equal(headers.get("X-IROS-Operator-ID"), OPERATOR_ID);
  assert.equal(headers.get("X-IROS-Security-ID"), SECURITY_ID);
  assert.equal(headers.get("X-IROS-Confirm-Embedded-Issuer-Hosts"), "true");
  assert.deepEqual(
    [...new Uint8Array(await (capturedBody as Blob).arrayBuffer())],
    [80, 75, 3, 4],
  );
  assert.equal(result.captureRevision, 1);
});

test("importResearchCaptureUpload requires explicit embedded-host confirmation", async () => {
  await assert.rejects(() =>
    importResearchCaptureUpload(
      {
        archive: new Blob([new Uint8Array([1])]),
        cik: "0001601830",
        confirmEmbeddedIssuerHosts: false,
        issuerName: "Recursion Pharmaceuticals, Inc.",
        operatorId: OPERATOR_ID,
        primaryListingExchange: "NASDAQ",
        securityId: SECURITY_ID,
      },
      READY_ENVIRONMENT,
      async () => {
        throw new Error("must not be called");
      },
    ),
  );
});
