import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  parsePersonalResearchValuationSnapshot,
  parseResearchValuationSnapshot,
  type PersonalResearchValuationSnapshot,
} from "./personal-research-valuation-snapshot.ts";
import { parseValuationSnapshot } from "./valuation-snapshot.ts";

const strictFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/contracts/valuation_snapshot/v1/valid-aligned.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Record<string, any>;

function personalFixture(): Record<string, any> {
  const fixture = structuredClone(strictFixture);
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
            locator: "RXRX consolidated EOD close 2026-05-06",
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
  return fixture;
}

function personalV2Fixture(): Record<string, any> {
  const fixture = personalFixture();
  fixture.contract_version = "valuation_snapshot.personal_research.v2";
  fixture.other_enterprise_claims = {
    ...fixture.other_included_claims,
    input_id: "other_enterprise_claims",
  };
  delete fixture.other_included_claims;
  fixture.other_enterprise_claim_components = [
    "redeemable_preferred_claim",
    "noncontrolling_interest_claim",
    "royalty_monetization_liability",
    "contingent_consideration_claim",
    "pension_underfunded_claim",
    "finance_lease_claim",
  ].map((componentId, index) => ({
    component_id: componentId,
    value: index === 0 ? "12000000" : "0",
    unit: "USD",
    period_end: "2026-02-28",
    effective_at: "2026-02-28T23:59:59+00:00",
    resolution: index === 0 ? "reported" : "structural_absence",
    reason_code: index === 0 ? "reported_balance" : "no_qualifying_claim",
    source_concept: index === 0 ? "RedeemablePreferredStock" : null,
    supporting_evidence_ids: ["55555555-5555-4555-8555-555555555555"],
    policy_version: "biotech-other-enterprise-claims-v1",
  }));
  fixture.enterprise_value.input_ids = fixture.enterprise_value.input_ids.map(
    (inputId: string) =>
      inputId === "other_included_claims"
        ? "other_enterprise_claims"
        : inputId,
  );
  fixture.enterprise_value.formula =
    "market capitalization + debt + other enterprise claims - included cash";
  return fixture;
}

test("personal research v2 dispatch preserves required research-only limitations", () => {
  const fixture = personalV2Fixture();

  const parsed = parseResearchValuationSnapshot(fixture);

  assert.deepEqual(parsed, fixture);
  assert.deepEqual(parsePersonalResearchValuationSnapshot(fixture), fixture);
  assert.deepEqual(parsed.valuation_assurance.limitation_codes, [
    "not_primary_venue_official_close",
    "not_institutional_grade",
    "not_for_trade_execution",
  ]);
});

test("research valuation dispatch rejects unknown versions and v2 legacy claim keys", () => {
  const unknownVersion = personalV2Fixture();
  unknownVersion.contract_version = "valuation_snapshot.personal_research.v3";

  const legacyClaim = personalV2Fixture();
  legacyClaim.other_included_claims = legacyClaim.other_enterprise_claims;

  assert.throws(
    () => parseResearchValuationSnapshot(unknownVersion),
    /invalid research valuation contract version/,
  );
  assert.throws(
    () => parsePersonalResearchValuationSnapshot(legacyClaim),
    TypeError,
  );
});

test("research valuation dispatch recognizes strict v2 without mixing assurance families", () => {
  const strictV2 = structuredClone(strictFixture);
  strictV2.contract_version = "valuation_snapshot.v2";
  strictV2.other_enterprise_claims = {
    ...strictV2.other_included_claims,
    input_id: "other_enterprise_claims",
  };
  delete strictV2.other_included_claims;
  strictV2.other_enterprise_claim_components = [
    "redeemable_preferred_claim",
    "noncontrolling_interest_claim",
    "royalty_monetization_liability",
    "contingent_consideration_claim",
    "pension_underfunded_claim",
    "finance_lease_claim",
  ].map((componentId, index) => ({
    component_id: componentId,
    value: index === 0 ? "12000000" : "0",
    unit: "USD",
    period_end: "2026-02-28",
    effective_at: "2026-02-28T23:59:59+00:00",
    resolution: index === 0 ? "reported" : "structural_absence",
    reason_code: index === 0 ? "reported_balance" : "no_qualifying_claim",
    source_concept: index === 0 ? "RedeemablePreferredStock" : null,
    supporting_evidence_ids: ["55555555-5555-4555-8555-555555555555"],
    policy_version: "biotech-other-enterprise-claims-v1",
  }));
  strictV2.enterprise_value.input_ids = strictV2.enterprise_value.input_ids.map(
    (inputId: string) =>
      inputId === "other_included_claims"
        ? "other_enterprise_claims"
        : inputId,
  );

  const parsed = parseResearchValuationSnapshot(strictV2);

  assert.equal(parsed.contract_version, "valuation_snapshot.v2");
  assert.equal("valuation_assurance" in parsed, false);
});

test("personal research valuation accepts verified consolidated EOD with explicit assurance and provenance", () => {
  const fixture = personalFixture();

  const parsed = parsePersonalResearchValuationSnapshot(fixture);

  assert.deepEqual(parsed, fixture);
  assert.equal(parsed.valuation_assurance.level, "personal_research");
  assert.equal(
    parsed.price_basis?.price_type,
    "verified_consolidated_end_of_day_close",
  );
  assert.equal(
    parsed.price_basis?.halt_verification_status,
    "verified_not_halted",
  );
  const marketSource = parsed.source_references.find(
    (source) => source.source_type === "personal_market_data",
  );
  assert.equal(marketSource?.provider_plan_id, "stocks_basic_personal");
  assert.equal(marketSource?.response_sha256, "b".repeat(64));
  assert.deepEqual(parseResearchValuationSnapshot(fixture), fixture);
  assert.deepEqual(parseResearchValuationSnapshot(strictFixture), strictFixture);
});

test("strict valuation parser remains closed to personal research semantics", () => {
  assert.throws(
    () => parseValuationSnapshot(personalFixture()),
    TypeError,
  );
  assert.deepEqual(parseValuationSnapshot(strictFixture), strictFixture);
});

test("personal research validation never fabricates licensed official-close provenance", () => {
  const source = readFileSync(
    new URL("./personal-research-valuation-snapshot.ts", import.meta.url),
    "utf8",
  );

  assert.doesNotMatch(source, /strictSurrogate/);
  assert.doesNotMatch(source, /official_unadjusted_close/);
  assert.doesNotMatch(source, /licensed_market_data/);
});

test("personal research valuation fails closed on assurance, provenance, halt, corporate-action, and materiality drift", () => {
  const candidate = () => personalFixture();

  const missingLimit = candidate();
  missingLimit.valuation_assurance.limitation_codes = [
    "not_primary_venue_official_close",
  ];

  const missingResponseHash = candidate();
  missingResponseHash.source_references[0].response_sha256 = null;

  const indeterminateHalt = candidate();
  indeterminateHalt.price_basis.halt_verification_status = "indeterminate";

  const unresolvedAction = candidate();
  unresolvedAction.corporate_action_reconciliation = {
    event_id: "split-2026",
    event_type: "stock_split",
    effective_at: "2026-05-01T13:30:00+00:00",
    price_adjustment_status: "unadjusted",
    share_count_adjustment_status: "indeterminate",
    reconciliation_result: "unresolved",
  };

  const indeterminateMateriality = candidate();
  indeterminateMateriality.evidence_materiality[0].publication_at = null;
  indeterminateMateriality.evidence_materiality[0].timing_state = "indeterminate";
  indeterminateMateriality.evidence_materiality[0].market_materiality =
    "indeterminate";
  indeterminateMateriality.price_information_state = "indeterminate";

  for (const [label, invalid] of Object.entries({
    missingLimit,
    missingResponseHash,
    indeterminateHalt,
    unresolvedAction,
    indeterminateMateriality,
  })) {
    assert.throws(
      () => parsePersonalResearchValuationSnapshot(invalid),
      TypeError,
      `${label} must fail closed`,
    );
  }
});

test("personal research valuation contract is separately published", () => {
  const publicTypes = readFileSync(new URL("./index.ts", import.meta.url), "utf8");
  const schema = JSON.parse(
    readFileSync(
      new URL(
        "./personal-research-valuation-snapshot.schema.json",
        import.meta.url,
      ),
      "utf8",
    ),
  ) as Record<string, any>;
  const v2Schema = JSON.parse(
    readFileSync(
      new URL(
        "./personal-research-valuation-snapshot.v2.schema.json",
        import.meta.url,
      ),
      "utf8",
    ),
  ) as Record<string, any>;

  assert.match(publicTypes, /parsePersonalResearchValuationSnapshot/);
  assert.match(publicTypes, /type PersonalResearchValuationSnapshot/);
  assert.equal(
    schema.properties.contract_version.const,
    "valuation_snapshot.personal_research.v1",
  );
  assert.equal(schema.additionalProperties, false);
  assert.equal(
    schema.$defs.price_basis.properties.price_type.const,
    "verified_consolidated_end_of_day_close",
  );
  assert.deepEqual(
    schema.$defs.price_basis.properties.halt_verification_status.enum,
    ["verified_not_halted", "halted", "indeterminate"],
  );
  assert.equal(
    v2Schema.properties.contract_version.const,
    "valuation_snapshot.personal_research.v2",
  );
  assert.equal(v2Schema.required.includes("other_included_claims"), false);
  assert.equal(v2Schema.required.includes("other_enterprise_claims"), true);
  assert.deepEqual(v2Schema.properties.other_enterprise_claims, {
    $ref: "valuation-snapshot.v2.schema.json#/$defs/capital_measure",
  });
  const requiredLimitations = v2Schema.$defs.valuation_assurance.properties
    .limitation_codes.allOf.map(
      (rule: Record<string, any>) => rule.contains.const,
    );
  assert.deepEqual(requiredLimitations, [
    "not_primary_venue_official_close",
    "not_institutional_grade",
    "not_for_trade_execution",
  ]);
});

void (undefined as unknown as PersonalResearchValuationSnapshot);
