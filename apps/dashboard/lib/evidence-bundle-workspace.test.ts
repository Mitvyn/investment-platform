import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { EvidenceBundle } from "../../../packages/types/evidence-bundle.ts";
import type { ResearchRun } from "../../../packages/types/research-run.ts";

import { presentEvidenceBundleWorkspace } from "./evidence-bundle-workspace.ts";

const runFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/research_run/v1/eligible.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as ResearchRun;

const bundleFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/evidence_bundle/v1/grader-ready.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as EvidenceBundle;

test("an eligible Research Run without a persisted bundle shows an explicit missing state", () => {
  assert.deepEqual(presentEvidenceBundleWorkspace(runFixture, null), {
    kind: "missing",
    description:
      "This eligible Research Run has no persisted Evidence Bundle yet.",
    status: { label: "Not materialized", variant: "attention" },
  });
});

test("a frozen bundle exposes exact audit identity, policies, and grader readiness", () => {
  const presentation = presentEvidenceBundleWorkspace(
    runFixture,
    bundleFixture,
  );

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  assert.deepEqual(presentation.status, {
    label: "Frozen",
    variant: "verified",
  });
  assert.deepEqual(presentation.readiness, {
    label: "Grader ready",
    variant: "verified",
    description: "Blocking primary evidence requirements are satisfied.",
  });
  assert.deepEqual(presentation.summary, [
    { label: "Bundle ID", value: bundleFixture.id },
    { label: "Bundle hash", value: bundleFixture.bundle_hash },
    { label: "Cutoff", value: bundleFixture.as_of_cutoff },
    { label: "Manifest items", value: String(bundleFixture.manifest.length) },
    {
      label: "Evidence policy",
      value: bundleFixture.evidence_policy_version,
    },
    {
      label: "Freshness policy",
      value: bundleFixture.freshness_policy_version,
    },
    { label: "Frozen", value: bundleFixture.created_at },
  ]);
  assert.deepEqual(presentation.gaps, []);
});

test("manifest presentation preserves canonical order and complete evidence provenance", () => {
  const presentation = presentEvidenceBundleWorkspace(
    runFixture,
    bundleFixture,
  );

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  assert.equal(presentation.manifest.length, bundleFixture.manifest.length);
  assert.deepEqual(presentation.manifest[0], {
    ordinal: "01",
    sourceClass: "SEC",
    itemKind: "Passage",
    sourceUrl: bundleFixture.manifest[0].source_locator,
    freshness: { label: "Current", variant: "verified" },
    fields: [
      { label: "Item ID", value: bundleFixture.manifest[0].item_id },
      {
        label: "Item version",
        value: bundleFixture.manifest[0].item_version_id,
      },
      { label: "Locator", value: bundleFixture.manifest[0].locator },
      {
        label: "Content SHA-256",
        value: bundleFixture.manifest[0].content_sha256,
      },
      { label: "Published", value: bundleFixture.manifest[0].published_at },
      { label: "Retrieved", value: bundleFixture.manifest[0].retrieved_at },
      { label: "Effective", value: bundleFixture.manifest[0].effective_at },
      {
        label: "Filing period",
        value: "2026-01-01 to 2026-03-31",
      },
      {
        label: "Freshness reason",
        value: bundleFixture.manifest[0].freshness_reason_code,
      },
      {
        label: "Freshness policy",
        value: bundleFixture.manifest[0].freshness_policy_version,
      },
    ],
  });
});

test("a blocked bundle exposes every deterministic evidence gap", () => {
  const blocked = structuredClone(bundleFixture);
  blocked.grader_ready = false;
  blocked.gaps = [
    {
      gap_id: "missing-authoritative-trial-record",
      requirement_id: "authoritative_trial",
      source_class: "clinical",
      reason_code: "missing_blocking_primary_evidence",
      explanation: "Authoritative trial evidence is unavailable at cutoff.",
    },
  ];

  const presentation = presentEvidenceBundleWorkspace(runFixture, blocked);

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  assert.deepEqual(presentation.readiness, {
    label: "Blocked",
    variant: "destructive",
    description: "Blocking primary evidence requirements remain unresolved.",
  });
  assert.deepEqual(presentation.gaps, [
    {
      id: "missing-authoritative-trial-record",
      requirement: "authoritative_trial",
      sourceClass: "Clinical",
      reason: "missing_blocking_primary_evidence",
      explanation: "Authoritative trial evidence is unavailable at cutoff.",
    },
  ]);
});

test("workspace rejects a bundle outside the Research Run evidence boundary", () => {
  const mismatchedSecurity = structuredClone(bundleFixture);
  mismatchedSecurity.security_id = "11111111-1111-4111-8111-111111111111";
  mismatchedSecurity.security_identity.id = mismatchedSecurity.security_id;

  assert.throws(
    () => presentEvidenceBundleWorkspace(runFixture, mismatchedSecurity),
    /does not match Research Run/,
  );

  const mismatchedCutoff = structuredClone(bundleFixture);
  mismatchedCutoff.as_of_cutoff = "2026-05-07T23:59:59+00:00";
  assert.throws(
    () => presentEvidenceBundleWorkspace(runFixture, mismatchedCutoff),
    /does not match Research Run/,
  );
});
