import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseValuationSnapshot } from "./valuation-snapshot.ts";

const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/valuation_snapshot/v1/valid-aligned.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as unknown;

test("TypeScript accepts canonical valid aligned valuation snapshot without semantic drift", () => {
  assert.deepEqual(parseValuationSnapshot(fixture), fixture);
});

test("Valuation Snapshot accepts only official unadjusted completed-session close", () => {
  const candidate = () => structuredClone(fixture) as Record<string, any>;

  const intraday = candidate();
  intraday.price_basis.price_type = "intraday";

  const adjusted = candidate();
  adjusted.price_basis.corporate_action_adjustment_status = "adjusted";

  const extendedHours = candidate();
  extendedHours.price_basis.session_type = "after_hours";

  const halted = candidate();
  halted.price_basis.market_status = "halted";

  const wrongSessionDate = candidate();
  wrongSessionDate.price_basis.session_date = "2026-05-05";

  for (const [label, invalid] of Object.entries({
    intraday,
    adjusted,
    extendedHours,
    halted,
    wrongSessionDate,
  })) {
    assert.throws(
      () => parseValuationSnapshot(invalid),
      TypeError,
      `${label} must fail closed`,
    );
  }
});

test("Valuation Snapshot requires typed capital inputs and resolved calculation provenance", () => {
  const candidate = () => structuredClone(fixture) as Record<string, any>;

  const numericShares = candidate();
  numericShares.basic_shares_outstanding.value = 357000000;

  const missingFormula = candidate();
  missingFormula.fully_diluted_shares.formula = null;

  const unresolvedSource = candidate();
  unresolvedSource.price_basis.provider_source_reference_id = "missing-source";

  const unresolvedCalculation = candidate();
  unresolvedCalculation.calculation_ids = ["unknown-calculation"];

  const portfolioState = candidate();
  portfolioState.available_cash = "100000";

  for (const [label, invalid] of Object.entries({
    numericShares,
    missingFormula,
    unresolvedSource,
    unresolvedCalculation,
    portfolioState,
  })) {
    assert.throws(
      () => parseValuationSnapshot(invalid),
      TypeError,
      `${label} must fail closed`,
    );
  }
});

test("Valuation Snapshot gates market-relative analysis on reconciliation and information alignment", () => {
  const candidate = () => structuredClone(fixture) as Record<string, any>;

  const actionMismatch = candidate();
  actionMismatch.corporate_action_reconciliation.reconciliation_result =
    "mismatch";

  const alignedAfterMaterialEvidence = candidate();
  alignedAfterMaterialEvidence.evidence_materiality[0].publication_at =
    "2026-05-06T21:00:00+00:00";
  alignedAfterMaterialEvidence.evidence_materiality[0].timing_state =
    "after_close_before_or_at_cutoff";

  const preMaterialPermitted = candidate();
  preMaterialPermitted.price_information_state = "pre_material_evidence";

  const indeterminatePermitted = candidate();
  indeterminatePermitted.price_information_state = "indeterminate";

  const invalidWithoutReason = candidate();
  invalidWithoutReason.snapshot_status = "invalid";
  invalidWithoutReason.market_relative_analysis_permitted = false;

  for (const [label, invalid] of Object.entries({
    actionMismatch,
    alignedAfterMaterialEvidence,
    preMaterialPermitted,
    indeterminatePermitted,
    invalidWithoutReason,
  })) {
    assert.throws(
      () => parseValuationSnapshot(invalid),
      TypeError,
      `${label} must fail closed`,
    );
  }
});

test("Valuation Snapshot rejects stale required capital input as valid", () => {
  const stale = structuredClone(fixture) as Record<string, any>;
  stale.cash.freshness_state = "stale";
  stale.cash.freshness_reason_code = "filing_outside_allowed_period";

  assert.throws(() => parseValuationSnapshot(stale), TypeError);
});

test("Valuation Snapshot fails closed on incomplete or mismatched cash and claims inputs", () => {
  const candidate = () => structuredClone(fixture) as Record<string, any>;

  const missingTreatment = candidate();
  delete missingTreatment.cash_treatment;

  const mismatchedCash = candidate();
  mismatchedCash.cash.value = "660200001";

  const mismatchedEffectiveAt = candidate();
  mismatchedEffectiveAt.cash_treatment.restricted_cash.effective_at =
    "2026-02-28T23:59:59+00:00";

  const missingClaims = candidate();
  missingClaims.other_included_claims = null;

  for (const [label, invalid] of Object.entries({
    missingTreatment,
    mismatchedCash,
    mismatchedEffectiveAt,
    missingClaims,
  })) {
    assert.throws(
      () => parseValuationSnapshot(invalid),
      TypeError,
      `${label} must fail closed`,
    );
  }
});

test("Valuation Snapshot preserves non-aligned and invalid outcomes without permitting market-relative analysis", () => {
  const preMaterial = structuredClone(fixture) as Record<string, any>;
  preMaterial.evidence_materiality[0].publication_at =
    "2026-05-06T21:00:00+00:00";
  preMaterial.evidence_materiality[0].timing_state =
    "after_close_before_or_at_cutoff";
  preMaterial.price_information_state = "pre_material_evidence";
  preMaterial.market_relative_analysis_permitted = false;

  const indeterminate = structuredClone(fixture) as Record<string, any>;
  indeterminate.evidence_materiality[0].publication_at = null;
  indeterminate.evidence_materiality[0].timing_state = "indeterminate";
  indeterminate.evidence_materiality[0].market_materiality = "indeterminate";
  indeterminate.price_information_state = "indeterminate";
  indeterminate.market_relative_analysis_permitted = false;

  const invalidAction = structuredClone(fixture) as Record<string, any>;
  invalidAction.snapshot_status = "invalid";
  invalidAction.invalid_reason_codes = ["corporate_action_basis_mismatch"];
  invalidAction.corporate_action_reconciliation = {
    event_id: "split-2026",
    event_type: "stock_split",
    effective_at: "2026-05-01T13:30:00+00:00",
    price_adjustment_status: "unadjusted",
    share_count_adjustment_status: "unadjusted",
    reconciliation_result: "mismatch",
  };
  invalidAction.market_relative_analysis_permitted = false;

  for (const result of [preMaterial, indeterminate, invalidAction]) {
    assert.deepEqual(parseValuationSnapshot(result), result);
  }
});

test("Valuation Snapshot contract is published through package root and strict JSON Schema", () => {
  const publicTypes = readFileSync(new URL("./index.ts", import.meta.url), "utf8");
  const schema = JSON.parse(
    readFileSync(
      new URL("./valuation-snapshot.schema.json", import.meta.url),
      "utf8",
    ),
  ) as Record<string, any>;

  assert.match(publicTypes, /parseValuationSnapshot/);
  assert.match(publicTypes, /type ValuationSnapshot/);
  assert.equal(schema.$schema, "https://json-schema.org/draft/2020-12/schema");
  assert.equal(
    schema.properties.contract_version.const,
    "valuation_snapshot.v1",
  );
  assert.equal(schema.additionalProperties, false);
  assert.deepEqual(schema.properties.price_information_state.enum, [
    "aligned",
    "pre_material_evidence",
    "indeterminate",
  ]);
  assert.equal(
    schema.$defs.price_basis.properties.price_type.const,
    "official_unadjusted_close",
  );
  assert.equal(schema.$defs.capital_measure.additionalProperties, false);
  assert.equal(schema.$defs.cash_treatment.additionalProperties, false);
});
