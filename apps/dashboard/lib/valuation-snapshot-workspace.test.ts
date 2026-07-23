import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { ResearchRun } from "../../../packages/types/research-run.ts";
import type { ValuationSnapshot } from "../../../packages/types/valuation-snapshot.ts";

import { presentValuationSnapshotWorkspace } from "./valuation-snapshot-workspace.ts";

const runFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/research_run/v1/eligible.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as ResearchRun;

const snapshotFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/valuation_snapshot/v1/valid-aligned.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as ValuationSnapshot;

test("a Research Run without a persisted valuation shows an explicit missing state", () => {
  assert.deepEqual(presentValuationSnapshotWorkspace(runFixture, null), {
    kind: "missing",
    description:
      "This Research Run has no persisted point-in-time Valuation Snapshot yet.",
    status: { label: "Not materialized", variant: "attention" },
  });
});

test("a valid aligned snapshot exposes official close, capital inputs, calculations, and reconciliation", () => {
  const presentation = presentValuationSnapshotWorkspace(
    runFixture,
    snapshotFixture,
  );

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  assert.deepEqual(presentation.status, {
    label: "Valid snapshot",
    variant: "verified",
  });
  assert.deepEqual(presentation.alignment, {
    label: "Aligned",
    variant: "verified",
    description:
      "Official close reflects all market-material evidence in this Research Run.",
  });
  assert.deepEqual(presentation.marketRelativeAnalysis, {
    label: "Market-relative analysis permitted",
    variant: "verified",
  });
  assert.deepEqual(presentation.priceBasis, {
    headline: "USD 6.20",
    fields: [
      { label: "Price type", value: "official_unadjusted_close" },
      { label: "Session", value: "2026-05-06" },
      { label: "Session type", value: "regular_us_trading_session" },
      { label: "Exchange", value: "NASDAQ" },
      { label: "Official close", value: "2026-05-06T20:00:00+00:00" },
      { label: "Market status", value: "closed" },
      { label: "Price adjustment", value: "unadjusted" },
      { label: "Calendar", value: "us-market-calendar-v1" },
      { label: "Input ID", value: "official_close" },
      { label: "Source reference", value: "market-close-source" },
    ],
  });
  assert.deepEqual(
    presentation.capitalInputs.map(({ label, value, unit }) => ({
      label,
      value,
      unit,
    })),
    [
      { label: "Basic shares", value: "357000000", unit: "shares" },
      { label: "Fully diluted shares", value: "383000000", unit: "shares" },
      { label: "Cash", value: "665200000", unit: "USD" },
      { label: "Debt", value: "5100000", unit: "USD" },
    ],
  );
  assert.deepEqual(
    presentation.derivedValues.map(
      ({ label, value, formula, formulaVersion, calculationId }) => ({
        label,
        value,
        formula,
        formulaVersion,
        calculationId,
      }),
    ),
    [
      {
        label: "Market capitalization",
        value: "2374600000 USD",
        formula: "share price * fully diluted shares",
        formulaVersion: "market-capitalization-v1",
        calculationId: "market-capitalization-result",
      },
      {
        label: "Enterprise value",
        value: "1714500000 USD",
        formula: "market capitalization + debt - cash",
        formulaVersion: "enterprise-value-v1",
        calculationId: "enterprise-value-result",
      },
    ],
  );
  assert.deepEqual(presentation.corporateAction, {
    event: "none",
    eventId: "Not applicable",
    effective: "Not applicable",
    priceAdjustment: "unadjusted",
    shareCountAdjustment: "not_applicable",
    result: "not_required",
  });
});

test("invalid and pre-material-evidence states remain distinct and block market-relative analysis", () => {
  const invalid = structuredClone(snapshotFixture);
  invalid.snapshot_status = "invalid";
  invalid.invalid_reason_codes = ["market_halted"];
  invalid.price_information_state = "indeterminate";
  invalid.market_relative_analysis_permitted = false;

  const invalidPresentation = presentValuationSnapshotWorkspace(
    runFixture,
    invalid,
  );
  assert.equal(invalidPresentation.kind, "ready");
  if (invalidPresentation.kind !== "ready") return;
  assert.deepEqual(invalidPresentation.status, {
    label: "Invalid snapshot",
    variant: "destructive",
  });
  assert.deepEqual(invalidPresentation.alignment, {
    label: "Indeterminate",
    variant: "attention",
    description:
      "Evidence timing or materiality cannot be aligned reliably to the official close.",
  });
  assert.deepEqual(invalidPresentation.marketRelativeAnalysis, {
    label: "Market-relative analysis blocked",
    variant: "destructive",
  });
  assert.deepEqual(invalidPresentation.invalidReasons, [
    { code: "market_halted", label: "market halted" },
  ]);

  const misaligned = structuredClone(snapshotFixture);
  misaligned.price_information_state = "pre_material_evidence";
  misaligned.market_relative_analysis_permitted = false;
  const misalignedPresentation = presentValuationSnapshotWorkspace(
    runFixture,
    misaligned,
  );
  assert.equal(misalignedPresentation.kind, "ready");
  if (misalignedPresentation.kind !== "ready") return;
  assert.equal(misalignedPresentation.status.variant, "verified");
  assert.equal(misalignedPresentation.alignment.variant, "attention");
  assert.equal(misalignedPresentation.marketRelativeAnalysis.variant, "attention");
});

test("capital inputs expose policy-derived freshness state and reason", () => {
  const presentation = presentValuationSnapshotWorkspace(
    runFixture,
    snapshotFixture,
  );

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  const basicShares = presentation.capitalInputs[0];
  assert.deepEqual(basicShares.fields.slice(-3), [
    { label: "Freshness", value: "current" },
    {
      label: "Freshness reason",
      value: "latest_required_filing_at_cutoff",
    },
    {
      label: "Freshness policy",
      value: "biotech-valuation-freshness-v1",
    },
  ]);
});

test("workspace rejects a Valuation Snapshot outside the Research Run boundary", () => {
  const wrongSecurity = structuredClone(snapshotFixture);
  wrongSecurity.security_id = "11111111-1111-4111-8111-111111111111";

  assert.throws(
    () => presentValuationSnapshotWorkspace(runFixture, wrongSecurity),
    /outside Research Run valuation boundary/,
  );
});
