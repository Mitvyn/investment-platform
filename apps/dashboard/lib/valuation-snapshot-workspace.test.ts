import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { ResearchRun } from "../../../packages/types/research-run.ts";
import type { PersonalResearchValuationSnapshot } from "../../../packages/types/personal-research-valuation-snapshot.ts";
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

const personalRunFixture = {
  ...runFixture,
  question_type:
    "biotech_moonshot_catalyst_personal_research_assessment",
  question_type_version:
    "biotech_moonshot_catalyst_personal_research_assessment.v1",
  workflow_config_version:
    "biotech-moonshot-catalyst-personal-research-v1",
  thesis_contract_id:
    "biotech_moonshot_catalyst_personal_research_v1",
} satisfies ResearchRun;

const snapshotFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../tests/fixtures/contracts/valuation_snapshot/v1/valid-aligned.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as ValuationSnapshot;

function personalSnapshotFixture(): PersonalResearchValuationSnapshot {
  const fixture = structuredClone(snapshotFixture) as Record<string, any>;
  fixture.contract_version = "valuation_snapshot.personal_research.v1";
  fixture.valuation_assurance = {
    level: "personal_research",
    usage_scope: "private_personal_research",
    rights_assurance: "not_independently_verified",
    limitation_codes: [
      "not_primary_venue_official_close",
      "not_institutional_grade",
      "not_for_trade_execution",
    ],
  };
  fixture.price_basis = {
    ...fixture.price_basis,
    input_id: "consolidated_eod_close",
    price_type: "verified_consolidated_end_of_day_close",
    price_timestamp: fixture.price_basis.official_close_timestamp,
    timestamp_basis: "market_calendar_session_close",
    halt_verification_status: "verified_not_halted",
  };
  delete fixture.price_basis.official_close_timestamp;
  fixture.market_capitalization.input_ids = [
    "consolidated_eod_close",
    "fully_diluted_shares",
  ];
  fixture.source_references = fixture.source_references.map(
    (source: Record<string, any>) =>
      source.source_reference_id === "market-close-source"
        ? {
            ...source,
            source_type: "personal_market_data",
            provider: "massive_stocks_basic",
            provider_plan_id: "stocks_basic_personal",
            provider_contract_status: "candidate_unapproved",
            provider_limitation_codes: [
              "official_close_provenance_unconfirmed",
              "persistence_rights_unconfirmed",
            ],
            response_sha256: "b".repeat(64),
          }
        : {
            ...source,
            provider_plan_id: null,
            provider_contract_status: null,
            provider_limitation_codes: [],
            response_sha256: null,
          },
  );
  fixture.price_basis_policy_version =
    "verified-consolidated-eod-close-personal-research-v1";
  return fixture as PersonalResearchValuationSnapshot;
}

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
      { label: "Reported cash", value: "665200000", unit: "USD" },
      {
        label: "Restricted cash (excluded)",
        value: "5000000",
        unit: "USD",
      },
      { label: "Included cash", value: "660200000", unit: "USD" },
      { label: "Debt", value: "5100000", unit: "USD" },
      { label: "Other included claims", value: "12000000", unit: "USD" },
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
        value: "1731500000 USD",
        formula:
          "market capitalization + debt + other included claims - included cash",
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

test("personal research snapshot exposes assurance and consolidated EOD provenance without claiming official close", () => {
  const presentation = presentValuationSnapshotWorkspace(
    personalRunFixture,
    personalSnapshotFixture(),
  );

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  assert.deepEqual(presentation.assurance, {
    label: "Personal research",
    variant: "attention",
    description:
      "Consolidated end-of-day price is not a primary-venue official close and is not institutional-grade.",
    usageScope: "private_personal_research",
    rightsAssurance: "not_independently_verified",
    limitationCodes: [
      "not_primary_venue_official_close",
      "not_institutional_grade",
      "not_for_trade_execution",
    ],
  });
  assert.equal(
    presentation.alignment.description,
    "Consolidated EOD price reflects all market-material evidence in this Research Run.",
  );
  assert.deepEqual(
    presentation.priceBasis?.fields.find(
      (field) => field.label === "Price timestamp",
    ),
    {
      label: "Price timestamp",
      value: "2026-05-06T20:00:00+00:00",
    },
  );
  assert.equal(
    presentation.priceBasis?.fields.some(
      (field) => field.label === "Official close",
    ),
    false,
  );
  assert.deepEqual(
    presentation.sourceReferences.find(
      (source) => source.type === "personal_market_data",
    ),
    {
      id: "market-close-source",
      type: "personal_market_data",
      provider: "massive_stocks_basic",
      providerPlan: "stocks_basic_personal",
      providerContractStatus: "candidate_unapproved",
      providerLimitationCodes: [
        "official_close_provenance_unconfirmed",
        "persistence_rights_unconfirmed",
      ],
      providerProvenanceVariant: "attention",
      locator: "RXRX official close 2026-05-06",
      published: "2026-05-06T20:00:00+00:00",
      retrieved: "2026-05-07T01:00:00+00:00",
      effective: "2026-05-06T20:00:00+00:00",
      responseSha256: "b".repeat(64),
    },
  );
  assert.equal(
    presentation.sourceReferences.some(
      (source) => "providerContractStatus" in source,
    ),
    true,
  );
});

test("strict valuation source references do not gain personal provider caveats", () => {
  const presentation = presentValuationSnapshotWorkspace(
    runFixture,
    snapshotFixture,
  );

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  assert.equal(
    presentation.sourceReferences.some(
      (source) => "providerContractStatus" in source,
    ),
    false,
  );
});

test("valuation snapshot contract must match Research Run thesis contract", () => {
  assert.throws(
    () => presentValuationSnapshotWorkspace(runFixture, personalSnapshotFixture()),
    /outside Research Run valuation contract/,
  );
  assert.throws(
    () => presentValuationSnapshotWorkspace(personalRunFixture, snapshotFixture),
    /outside Research Run valuation contract/,
  );
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
