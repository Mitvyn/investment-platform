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
});

void (undefined as unknown as PersonalResearchValuationSnapshot);
