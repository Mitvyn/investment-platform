import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseEvidenceBundle } from "./evidence-bundle.ts";

const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/evidence_bundle/v1/grader-ready.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as unknown;

test("TypeScript accepts canonical grader-ready Evidence Bundle without semantic drift", () => {
  assert.deepEqual(parseEvidenceBundle(fixture), fixture);
});

test("Evidence Bundle snapshots use typed decimal values and resolve manifest evidence", () => {
  const candidate = () => structuredClone(fixture) as Record<string, any>;

  const numericMetric = candidate();
  numericMetric.verified_metrics[0].value = 665.2;

  const unresolvedSupport = candidate();
  unresolvedSupport.catalysts[0].supporting_evidence_ids = [
    "99999999-9999-4999-8999-999999999999",
  ];

  const wrongManifestKind = candidate();
  wrongManifestKind.manifest[6].item_kind = "risk";

  const invalidCatalystBasis = candidate();
  invalidCatalystBasis.catalysts[0].basis = "commercial";

  const extraRiskField = candidate();
  extraRiskField.risks[0].probability = "0.5";

  for (const [label, invalid] of Object.entries({
    numericMetric,
    unresolvedSupport,
    wrongManifestKind,
    invalidCatalystBasis,
    extraRiskField,
  })) {
    assert.throws(
      () => parseEvidenceBundle(invalid),
      TypeError,
      `${label} must fail closed`,
    );
  }
});

test("Evidence Bundle manifest is unique, canonically ordered, and cutoff safe", () => {
  const candidate = () => structuredClone(fixture) as Record<string, any>;

  const reordered = candidate();
  [reordered.manifest[0], reordered.manifest[1]] = [
    reordered.manifest[1],
    reordered.manifest[0],
  ];
  reordered.manifest.forEach(
    (item: Record<string, unknown>, index: number) => (item.ordinal = index + 1),
  );

  const duplicateItem = candidate();
  duplicateItem.manifest[1].item_id = duplicateItem.manifest[0].item_id;

  const postCutoff = candidate();
  postCutoff.manifest[0].published_at = "2026-05-07T00:00:00+00:00";

  const reversedFilingPeriod = candidate();
  reversedFilingPeriod.manifest[0].filing_period_start = "2026-04-01";

  const wrongFreshnessPolicy = candidate();
  wrongFreshnessPolicy.manifest[0].freshness_policy_version =
    "biotech-evidence-freshness-v2";

  for (const [label, invalid] of Object.entries({
    reordered,
    duplicateItem,
    postCutoff,
    reversedFilingPeriod,
    wrongFreshnessPolicy,
  })) {
    assert.throws(
      () => parseEvidenceBundle(invalid),
      TypeError,
      `${label} must fail closed`,
    );
  }
});

test("Evidence Bundle keeps incomplete evidence auditable but blocks grader readiness", () => {
  const candidate = () => structuredClone(fixture) as Record<string, any>;
  const gap = {
    gap_id: "missing-authoritative-trial-record",
    requirement_id: "authoritative_trial",
    source_class: "clinical",
    reason_code: "missing_blocking_primary_evidence",
    explanation: "Authoritative trial evidence is unavailable at cutoff.",
  };

  const blocked = candidate();
  blocked.manifest = blocked.manifest.filter(
    (item: Record<string, unknown>) => item.source_class !== "clinical",
  );
  blocked.manifest.forEach(
    (item: Record<string, unknown>, index: number) => (item.ordinal = index + 1),
  );
  blocked.catalysts = [];
  blocked.grader_ready = false;
  blocked.gaps = [gap];

  assert.deepEqual(parseEvidenceBundle(blocked), blocked);

  const readyWithGap = candidate();
  readyWithGap.gaps = [gap];

  const readyMissingSource = structuredClone(blocked);
  readyMissingSource.grader_ready = true;
  readyMissingSource.gaps = [];

  const blockedWithoutGap = candidate();
  blockedWithoutGap.grader_ready = false;

  const readyWithFailedEligibility = candidate();
  readyWithFailedEligibility.eligibility.eligible = false;
  readyWithFailedEligibility.eligibility.checks[8].passed = false;

  for (const [label, invalid] of Object.entries({
    readyWithGap,
    readyMissingSource,
    blockedWithoutGap,
    readyWithFailedEligibility,
  })) {
    assert.throws(
      () => parseEvidenceBundle(invalid),
      TypeError,
      `${label} must fail closed`,
    );
  }
});

test("Evidence Bundle rejects generated and model-derived inputs", () => {
  const candidate = () => structuredClone(fixture) as Record<string, any>;

  const modelSource = candidate();
  modelSource.manifest[0].source_class = "model";

  const opinionItem = candidate();
  opinionItem.manifest[0].item_kind = "opinion";

  const generatedLocator = candidate();
  generatedLocator.manifest[0].source_locator =
    "generated://model-supplied-source";

  const committeeOutput = candidate();
  committeeOutput.committee_output = { summary: "Not evidence." };

  for (const [label, invalid] of Object.entries({
    modelSource,
    opinionItem,
    generatedLocator,
    committeeOutput,
  })) {
    assert.throws(
      () => parseEvidenceBundle(invalid),
      TypeError,
      `${label} must fail closed`,
    );
  }
});

test("Evidence Bundle contract is published through package root and versioned JSON Schema", () => {
  const publicTypes = readFileSync(new URL("./index.ts", import.meta.url), "utf8");
  const schema = JSON.parse(
    readFileSync(new URL("./evidence-bundle.schema.json", import.meta.url), "utf8"),
  ) as Record<string, any>;

  assert.match(publicTypes, /parseEvidenceBundle/);
  assert.match(publicTypes, /type EvidenceBundle/);
  assert.equal(schema.$schema, "https://json-schema.org/draft/2020-12/schema");
  assert.equal(
    schema.properties.contract_version.const,
    "evidence_bundle.v1",
  );
  assert.deepEqual(schema.$defs.manifest_entry.properties.source_class.enum, [
    "sec",
    "issuer",
    "clinical",
    "regulatory",
    "financing",
  ]);
  assert.deepEqual(schema.$defs.verified_metric.properties.value, {
    type: "string",
    pattern: "^-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?$",
  });
});
