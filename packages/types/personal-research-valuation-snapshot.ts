import {
  parseValuationSnapshot,
  validateValuationSnapshotStructure,
  type PriceBasis,
  type ValuationSnapshot,
  type ValuationSnapshotV1,
  type ValuationSnapshotV2,
  type ValuationSourceReference,
} from "./valuation-snapshot.ts";

export type PersonalResearchValuationAssurance = {
  level: "personal_research";
  usage_scope: "private_personal_research";
  rights_assurance: "not_independently_verified";
  limitation_codes: string[];
};

export type PersonalResearchPriceBasis = Omit<
  PriceBasis,
  "price_type" | "official_close_timestamp"
> & {
  price_type: "verified_consolidated_end_of_day_close";
  price_timestamp: string;
  timestamp_basis: "market_calendar_session_close";
  halt_verification_status:
    | "verified_not_halted"
    | "halted"
    | "indeterminate";
};

export type PersonalResearchValuationSourceReference = Omit<
  ValuationSourceReference,
  "source_type"
> & {
  source_type: "personal_market_data" | "primary_filing";
  provider_plan_id: string | null;
  response_sha256: string | null;
  provider_contract_status: string | null;
  provider_limitation_codes: string[];
};

type PersonalResearchValuationSnapshotV1 = Omit<
  ValuationSnapshotV1,
  "contract_version" | "price_basis" | "source_references"
> & {
  contract_version: "valuation_snapshot.personal_research.v1";
  valuation_assurance: PersonalResearchValuationAssurance;
  price_basis: PersonalResearchPriceBasis | null;
  source_references: PersonalResearchValuationSourceReference[];
};

type PersonalResearchValuationSnapshotV2 = Omit<
  ValuationSnapshotV2,
  "contract_version" | "price_basis" | "source_references"
> & {
  contract_version: "valuation_snapshot.personal_research.v2";
  valuation_assurance: PersonalResearchValuationAssurance;
  price_basis: PersonalResearchPriceBasis | null;
  source_references: PersonalResearchValuationSourceReference[];
};

export type PersonalResearchValuationSnapshot =
  | PersonalResearchValuationSnapshotV1
  | PersonalResearchValuationSnapshotV2;

export type ResearchValuationSnapshot =
  | ValuationSnapshot
  | PersonalResearchValuationSnapshot;

const SNAPSHOT_KEYS_BASE = [
  "contract_version",
  "id",
  "operator_id",
  "research_run_id",
  "evidence_bundle_id",
  "evidence_bundle_hash",
  "security_id",
  "as_of_cutoff",
  "snapshot_status",
  "invalid_reason_codes",
  "currency",
  "valuation_assurance",
  "price_basis",
  "basic_shares_outstanding",
  "dilution_instruments",
  "fully_diluted_shares",
  "cash",
  "cash_treatment",
  "debt",
  "market_capitalization",
  "enterprise_value",
  "source_references",
  "evidence_ids",
  "calculation_ids",
  "corporate_action_reconciliation",
  "evidence_materiality",
  "price_information_state",
  "market_relative_analysis_permitted",
  "price_basis_policy_version",
  "freshness_policy_version",
  "materiality_policy_version",
  "created_at",
] as const;

const SNAPSHOT_KEYS_V1 = [
  ...SNAPSHOT_KEYS_BASE,
  "other_included_claims",
] as const;

const SNAPSHOT_KEYS_V2 = [
  ...SNAPSHOT_KEYS_BASE,
  "other_enterprise_claims",
  "other_enterprise_claim_components",
] as const;

const ASSURANCE_KEYS = [
  "level",
  "usage_scope",
  "rights_assurance",
  "limitation_codes",
] as const;

const PRICE_BASIS_KEYS = [
  "input_id",
  "price_type",
  "session_type",
  "session_date",
  "primary_listing_exchange",
  "share_price",
  "price_timestamp",
  "timestamp_basis",
  "market_calendar_version",
  "market_status",
  "halt_verification_status",
  "corporate_action_adjustment_status",
  "provider_source_reference_id",
] as const;

const SOURCE_REFERENCE_KEYS = [
  "source_reference_id",
  "source_type",
  "provider",
  "provider_plan_id",
  "provider_contract_status",
  "provider_limitation_codes",
  "locator",
  "published_at",
  "retrieved_at",
  "effective_at",
  "response_sha256",
] as const;

const REQUIRED_LIMITATIONS = [
  "not_primary_venue_official_close",
  "not_institutional_grade",
  "not_for_trade_execution",
] as const;

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError(`invalid ${label}`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
  label: string,
) {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (
    actual.length !== expected.length ||
    actual.some((key, index) => key !== expected[index])
  ) {
    throw new TypeError(`invalid ${label} fields`);
  }
}

function nonEmptyString(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new TypeError(`invalid ${label}`);
  }
}

function timestamp(value: unknown, label: string): asserts value is string {
  nonEmptyString(value, label);
  if (
    !/(?:z|[+-]\d{2}:\d{2})$/i.test(value) ||
    Number.isNaN(Date.parse(value))
  ) {
    throw new TypeError(`invalid ${label}`);
  }
}

function sha256(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
    throw new TypeError(`invalid ${label}`);
  }
}

function stringArray(value: unknown, label: string): asserts value is string[] {
  if (
    !Array.isArray(value) ||
    value.some((item) => typeof item !== "string" || item.length === 0) ||
    new Set(value).size !== value.length
  ) {
    throw new TypeError(`invalid ${label}`);
  }
}

function parseAssurance(value: unknown): PersonalResearchValuationAssurance {
  const assurance = record(value, "valuation assurance");
  exactKeys(assurance, ASSURANCE_KEYS, "valuation assurance");
  if (
    assurance.level !== "personal_research" ||
    assurance.usage_scope !== "private_personal_research" ||
    assurance.rights_assurance !== "not_independently_verified"
  ) {
    throw new TypeError("invalid personal research valuation assurance");
  }
  stringArray(assurance.limitation_codes, "valuation limitation codes");
  if (
    REQUIRED_LIMITATIONS.some(
      (code) => !(assurance.limitation_codes as string[]).includes(code),
    )
  ) {
    throw new TypeError("personal research valuation limitations are incomplete");
  }
  return assurance as PersonalResearchValuationAssurance;
}

function parsePriceBasis(
  value: unknown,
  cutoff: string,
): PersonalResearchPriceBasis {
  const price = record(value, "personal research price basis");
  exactKeys(price, PRICE_BASIS_KEYS, "personal research price basis");
  nonEmptyString(price.input_id, "price basis input ID");
  if (
    price.price_type !== "verified_consolidated_end_of_day_close" ||
    price.session_type !== "regular_us_trading_session"
  ) {
    throw new TypeError("invalid personal research price type");
  }
  nonEmptyString(price.session_date, "price session date");
  nonEmptyString(price.primary_listing_exchange, "primary listing exchange");
  nonEmptyString(price.share_price, "share price");
  timestamp(price.price_timestamp, "price timestamp");
  if (price.timestamp_basis !== "market_calendar_session_close") {
    throw new TypeError("invalid price timestamp basis");
  }
  if (Date.parse(price.price_timestamp) > Date.parse(cutoff)) {
    throw new TypeError("price timestamp occurs after cutoff");
  }
  if (price.price_timestamp.slice(0, 10) !== price.session_date) {
    throw new TypeError("price timestamp does not match session date");
  }
  nonEmptyString(price.market_calendar_version, "market calendar version");
  if (!(["closed", "halted"] as unknown[]).includes(price.market_status)) {
    throw new TypeError("invalid market status");
  }
  if (
    !(["verified_not_halted", "halted", "indeterminate"] as unknown[]).includes(
      price.halt_verification_status,
    )
  ) {
    throw new TypeError("invalid halt verification status");
  }
  if (
    !(["unadjusted", "indeterminate"] as unknown[]).includes(
      price.corporate_action_adjustment_status,
    )
  ) {
    throw new TypeError("invalid price adjustment status");
  }
  nonEmptyString(price.provider_source_reference_id, "price source reference");
  return price as PersonalResearchPriceBasis;
}

function parseSourceReference(
  value: unknown,
): PersonalResearchValuationSourceReference {
  const source = record(value, "personal research valuation source");
  exactKeys(source, SOURCE_REFERENCE_KEYS, "personal research valuation source");
  nonEmptyString(source.source_reference_id, "source reference ID");
  if (!(["personal_market_data", "primary_filing"] as unknown[]).includes(source.source_type)) {
    throw new TypeError("invalid personal research source type");
  }
  nonEmptyString(source.provider, "source provider");
  nonEmptyString(source.locator, "source locator");
  timestamp(source.retrieved_at, "source retrieval timestamp");
  if (source.published_at !== null) timestamp(source.published_at, "source publication timestamp");
  if (source.effective_at !== null) timestamp(source.effective_at, "source effective timestamp");
  if (source.source_type === "personal_market_data") {
    nonEmptyString(source.provider_plan_id, "provider plan ID");
    nonEmptyString(source.provider_contract_status, "provider contract status");
    stringArray(
      source.provider_limitation_codes,
      "provider limitation codes",
    );
    if (
      source.provider_limitation_codes.length === 0 ||
      source.provider_limitation_codes.some(
        (code) => !/^[a-z][a-z0-9_]{0,127}$/.test(code),
      )
    ) {
      throw new TypeError("invalid provider limitation codes");
    }
    sha256(source.response_sha256, "market response hash");
  } else if (
    source.provider_plan_id !== null ||
    source.response_sha256 !== null ||
    source.provider_contract_status !== null ||
    !Array.isArray(source.provider_limitation_codes) ||
    source.provider_limitation_codes.length !== 0
  ) {
    throw new TypeError("primary filing cannot carry market provider provenance");
  }
  return source as PersonalResearchValuationSourceReference;
}

export function parsePersonalResearchValuationSnapshot(
  value: unknown,
): PersonalResearchValuationSnapshot {
  const snapshot = record(value, "Personal Research Valuation Snapshot");
  if (
    snapshot.contract_version !== "valuation_snapshot.personal_research.v1" &&
    snapshot.contract_version !== "valuation_snapshot.personal_research.v2"
  ) {
    throw new TypeError("invalid personal research valuation contract version");
  }
  exactKeys(
    snapshot,
    snapshot.contract_version === "valuation_snapshot.personal_research.v2"
      ? SNAPSHOT_KEYS_V2
      : SNAPSHOT_KEYS_V1,
    "Personal Research Valuation Snapshot",
  );
  parseAssurance(snapshot.valuation_assurance);
  nonEmptyString(snapshot.as_of_cutoff, "as_of_cutoff");
  const price =
    snapshot.price_basis === null
      ? null
      : parsePriceBasis(snapshot.price_basis, snapshot.as_of_cutoff);
  if (!Array.isArray(snapshot.source_references)) {
    throw new TypeError("invalid personal research source references");
  }
  const sources = snapshot.source_references.map(parseSourceReference);
  const sourceIds = sources.map((source) => source.source_reference_id);
  if (new Set(sourceIds).size !== sourceIds.length) {
    throw new TypeError("duplicate personal research source reference");
  }
  if (price !== null) {
    const source = sources.find(
      (candidate) =>
        candidate.source_reference_id === price.provider_source_reference_id,
    );
    if (source?.source_type !== "personal_market_data") {
      throw new TypeError("personal price provenance is unresolved");
    }
  }

  validateValuationSnapshotStructure(
    snapshot,
    price === null
      ? null
      : {
          input_id: price.input_id,
          timestamp: price.price_timestamp,
          market_status: price.market_status,
          corporate_action_adjustment_status:
            price.corporate_action_adjustment_status,
          provider_source_reference_id: price.provider_source_reference_id,
        },
    sourceIds,
  );

  const reasons = snapshot.invalid_reason_codes as string[];
  if (price !== null) {
    if (
      price.halt_verification_status === "verified_not_halted" &&
      price.market_status !== "closed"
    ) {
      throw new TypeError("halt verification conflicts with market status");
    }
    if (
      price.halt_verification_status !== "verified_not_halted" &&
      (snapshot.snapshot_status !== "invalid" ||
        snapshot.market_relative_analysis_permitted !== false)
    ) {
      throw new TypeError("unverified halt state must block personal valuation");
    }
    if (
      price.halt_verification_status === "halted" &&
      !reasons.includes("market_halted")
    ) {
      throw new TypeError("halted valuation requires market_halted reason");
    }
    if (
      price.halt_verification_status === "indeterminate" &&
      !reasons.includes("market_halt_status_indeterminate")
    ) {
      throw new TypeError("indeterminate halt valuation requires reason");
    }
  }
  if (
    snapshot.snapshot_status === "valid" &&
    price?.halt_verification_status !== "verified_not_halted"
  ) {
    throw new TypeError("valid personal valuation requires verified halt state");
  }
  return value as PersonalResearchValuationSnapshot;
}

export function parseResearchValuationSnapshot(
  value: unknown,
): ResearchValuationSnapshot {
  const snapshot = record(value, "Research Valuation Snapshot");
  if (
    snapshot.contract_version === "valuation_snapshot.personal_research.v1" ||
    snapshot.contract_version === "valuation_snapshot.personal_research.v2"
  ) {
    return parsePersonalResearchValuationSnapshot(snapshot);
  }
  if (
    snapshot.contract_version === "valuation_snapshot.v1" ||
    snapshot.contract_version === "valuation_snapshot.v2"
  ) {
    return parseValuationSnapshot(snapshot);
  }
  throw new TypeError("invalid research valuation contract version");
}
