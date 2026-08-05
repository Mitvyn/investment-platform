export type PriceInformationState =
  | "aligned"
  | "pre_material_evidence"
  | "indeterminate";

export type PriceBasis = {
  input_id: string;
  price_type: "official_unadjusted_close";
  session_type: "regular_us_trading_session";
  session_date: string;
  primary_listing_exchange: string;
  share_price: string;
  official_close_timestamp: string;
  market_calendar_version: string;
  market_status: "closed" | "halted";
  corporate_action_adjustment_status: "unadjusted" | "indeterminate";
  provider_source_reference_id: string;
};

export type CapitalMeasure = {
  input_id: string;
  value: string;
  unit: string;
  effective_at: string;
  calculation_method: "reported" | "calculated";
  formula: string | null;
  calculation_id: string | null;
  input_ids: string[];
  supporting_evidence_ids: string[];
  freshness_state: "current" | "stale" | "indeterminate";
  freshness_reason_code: string;
  freshness_policy_version: string;
};

export type CashTreatment = {
  reported_cash: CapitalMeasure;
  restricted_cash: CapitalMeasure;
  restricted_cash_treatment: "none" | "included" | "excluded";
};

export type DilutionInstrument = {
  instrument_id: string;
  instrument_type:
    | "options"
    | "warrants"
    | "convertibles"
    | "rsus"
    | "preferred"
    | "other";
  diluted_share_increment: string;
  effective_at: string;
  supporting_evidence_ids: string[];
};

export type DerivedValuation = {
  value: string;
  unit: string;
  formula: string;
  formula_version: string;
  input_ids: string[];
  calculation_id: string;
  supporting_evidence_ids: string[];
};

export type ValuationSourceReference = {
  source_reference_id: string;
  source_type: "licensed_market_data" | "primary_filing";
  provider: string;
  locator: string;
  published_at: string | null;
  retrieved_at: string;
  effective_at: string | null;
};

export type CorporateActionReconciliation = {
  event_id: string | null;
  event_type:
    | "none"
    | "stock_split"
    | "reverse_split"
    | "merger"
    | "conversion"
    | "ticker_change"
    | "exchange_change"
    | "spin_off"
    | "recapitalization"
    | "share_class_conversion"
    | "other";
  effective_at: string | null;
  price_adjustment_status:
    | "unadjusted"
    | "adjusted"
    | "not_applicable"
    | "indeterminate";
  share_count_adjustment_status:
    | "adjusted"
    | "unadjusted"
    | "not_applicable"
    | "indeterminate";
  reconciliation_result:
    | "reconciled"
    | "not_required"
    | "unresolved"
    | "mismatch";
};

export type MarketMateriality = {
  evidence_id: string;
  publication_at: string | null;
  timing_state:
    | "before_or_at_close"
    | "after_close_before_or_at_cutoff"
    | "indeterminate";
  market_materiality: "material" | "non_material" | "indeterminate";
  materiality_reason_code: string;
  materiality_policy_version: string;
  affected_domains: Array<
    | "catalyst"
    | "clinical"
    | "regulatory"
    | "financing"
    | "dilution"
    | "valuation"
    | "management"
    | "commercial"
  >;
};

export type ValuationSnapshot = {
  contract_version: "valuation_snapshot.v1";
  id: string;
  operator_id: string;
  research_run_id: string;
  evidence_bundle_id: string;
  evidence_bundle_hash: string;
  security_id: string;
  as_of_cutoff: string;
  snapshot_status: "valid" | "invalid";
  invalid_reason_codes: string[];
  currency: string;
  price_basis: PriceBasis | null;
  basic_shares_outstanding: CapitalMeasure | null;
  dilution_instruments: DilutionInstrument[];
  fully_diluted_shares: CapitalMeasure | null;
  cash: CapitalMeasure | null;
  cash_treatment: CashTreatment | null;
  debt: CapitalMeasure | null;
  other_included_claims: CapitalMeasure | null;
  market_capitalization: DerivedValuation | null;
  enterprise_value: DerivedValuation | null;
  source_references: ValuationSourceReference[];
  evidence_ids: string[];
  calculation_ids: string[];
  corporate_action_reconciliation: CorporateActionReconciliation;
  evidence_materiality: MarketMateriality[];
  price_information_state: PriceInformationState;
  market_relative_analysis_permitted: boolean;
  price_basis_policy_version: string;
  freshness_policy_version: string;
  materiality_policy_version: string;
  created_at: string;
};

const SNAPSHOT_KEYS = [
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
  "price_basis",
  "basic_shares_outstanding",
  "dilution_instruments",
  "fully_diluted_shares",
  "cash",
  "cash_treatment",
  "debt",
  "other_included_claims",
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

const PRICE_BASIS_KEYS = [
  "input_id",
  "price_type",
  "session_type",
  "session_date",
  "primary_listing_exchange",
  "share_price",
  "official_close_timestamp",
  "market_calendar_version",
  "market_status",
  "corporate_action_adjustment_status",
  "provider_source_reference_id",
] as const;

const CAPITAL_MEASURE_KEYS = [
  "input_id",
  "value",
  "unit",
  "effective_at",
  "calculation_method",
  "formula",
  "calculation_id",
  "input_ids",
  "supporting_evidence_ids",
  "freshness_state",
  "freshness_reason_code",
  "freshness_policy_version",
] as const;

const CASH_TREATMENT_KEYS = [
  "reported_cash",
  "restricted_cash",
  "restricted_cash_treatment",
] as const;

const DILUTION_INSTRUMENT_KEYS = [
  "instrument_id",
  "instrument_type",
  "diluted_share_increment",
  "effective_at",
  "supporting_evidence_ids",
] as const;

const DERIVED_VALUATION_KEYS = [
  "value",
  "unit",
  "formula",
  "formula_version",
  "input_ids",
  "calculation_id",
  "supporting_evidence_ids",
] as const;

const SOURCE_REFERENCE_KEYS = [
  "source_reference_id",
  "source_type",
  "provider",
  "locator",
  "published_at",
  "retrieved_at",
  "effective_at",
] as const;

const CORPORATE_ACTION_KEYS = [
  "event_id",
  "event_type",
  "effective_at",
  "price_adjustment_status",
  "share_count_adjustment_status",
  "reconciliation_result",
] as const;

const MARKET_MATERIALITY_KEYS = [
  "evidence_id",
  "publication_at",
  "timing_state",
  "market_materiality",
  "materiality_reason_code",
  "materiality_policy_version",
  "affected_domains",
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

function oneOf(value: unknown, allowed: readonly string[], label: string) {
  if (typeof value !== "string" || !allowed.includes(value)) {
    throw new TypeError(`invalid ${label}`);
  }
}

function nonEmptyString(value: unknown, label: string) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`invalid ${label}`);
  }
}

function date(value: unknown, label: string) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new TypeError(`invalid ${label}`);
  }
}

function timestamp(value: unknown, label: string) {
  nonEmptyString(value, label);
  if (
    !/(?:z|[+-]\d{2}:\d{2})$/i.test(value as string) ||
    Number.isNaN(Date.parse(value as string))
  ) {
    throw new TypeError(`invalid ${label}`);
  }
}

function decimal(value: unknown, label: string) {
  if (
    typeof value !== "string" ||
    !/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value)
  ) {
    throw new TypeError(`invalid ${label}`);
  }
}

function decimalParts(value: string): { coefficient: bigint; scale: number } {
  const [integer, fraction = ""] = value.split(".");
  const sign = integer.startsWith("-") ? -BigInt(1) : BigInt(1);
  const digits = `${integer.replace("-", "")}${fraction}`;
  return {
    coefficient: sign * BigInt(digits),
    scale: fraction.length,
  };
}

function compareDecimalValues(
  left: string,
  right: string,
): -1 | 0 | 1 {
  const leftParts = decimalParts(left);
  const rightParts = decimalParts(right);
  const scale = Math.max(leftParts.scale, rightParts.scale);
  const leftCoefficient =
    leftParts.coefficient * BigInt(10) ** BigInt(scale - leftParts.scale);
  const rightCoefficient =
    rightParts.coefficient * BigInt(10) ** BigInt(scale - rightParts.scale);
  return leftCoefficient === rightCoefficient
    ? 0
    : leftCoefficient < rightCoefficient
      ? -1
      : 1;
}

function subtractDecimalValues(left: string, right: string): string {
  const leftParts = decimalParts(left);
  const rightParts = decimalParts(right);
  const scale = Math.max(leftParts.scale, rightParts.scale);
  const coefficient =
    leftParts.coefficient * BigInt(10) ** BigInt(scale - leftParts.scale) -
    rightParts.coefficient * BigInt(10) ** BigInt(scale - rightParts.scale);
  if (scale === 0) return coefficient.toString();
  const sign = coefficient < BigInt(0) ? "-" : "";
  const digits = (coefficient < BigInt(0) ? -coefficient : coefficient)
    .toString()
    .padStart(scale + 1, "0");
  const integer = digits.slice(0, -scale);
  const fraction = digits.slice(-scale).replace(/0+$/, "");
  return fraction.length === 0
    ? `${sign}${integer}`
    : `${sign}${integer}.${fraction}`;
}

function stringArray(value: unknown, label: string) {
  if (
    !Array.isArray(value) ||
    value.some((item) => typeof item !== "string" || item.length === 0)
  ) {
    throw new TypeError(`invalid ${label}`);
  }
}

function uuid(value: unknown, label: string) {
  nonEmptyString(value, label);
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      value as string,
    )
  ) {
    throw new TypeError(`invalid ${label}`);
  }
}

function sha256(value: unknown, label: string) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
    throw new TypeError(`invalid ${label}`);
  }
}

function nullableTimestamp(value: unknown, label: string) {
  if (value !== null) timestamp(value, label);
}

function uniqueStrings(value: string[], label: string) {
  if (new Set(value).size !== value.length) {
    throw new TypeError(`duplicate ${label}`);
  }
}

function parsePriceBasis(value: unknown, cutoff: string): PriceBasis {
  const price = record(value, "price_basis");
  exactKeys(price, PRICE_BASIS_KEYS, "price_basis");
  nonEmptyString(price.input_id, "price_basis.input_id");
  oneOf(
    price.price_type,
    ["official_unadjusted_close"],
    "price_basis.price_type",
  );
  oneOf(
    price.session_type,
    ["regular_us_trading_session"],
    "price_basis.session_type",
  );
  date(price.session_date, "price_basis.session_date");
  nonEmptyString(
    price.primary_listing_exchange,
    "price_basis.primary_listing_exchange",
  );
  decimal(price.share_price, "price_basis.share_price");
  timestamp(
    price.official_close_timestamp,
    "price_basis.official_close_timestamp",
  );
  nonEmptyString(
    price.market_calendar_version,
    "price_basis.market_calendar_version",
  );
  oneOf(price.market_status, ["closed", "halted"], "price_basis.market_status");
  oneOf(
    price.corporate_action_adjustment_status,
    ["unadjusted", "indeterminate"],
    "price_basis.corporate_action_adjustment_status",
  );
  nonEmptyString(
    price.provider_source_reference_id,
    "price_basis.provider_source_reference_id",
  );
  if (Date.parse(price.official_close_timestamp as string) > Date.parse(cutoff)) {
    throw new TypeError("price close occurs after cutoff");
  }
  if (
    (price.official_close_timestamp as string).slice(0, 10) !==
    price.session_date
  ) {
    throw new TypeError("official close does not match session date");
  }
  return price as PriceBasis;
}

function parseCapitalMeasure(
  value: unknown,
  label: string,
  cutoff: string,
): CapitalMeasure {
  const measure = record(value, label);
  exactKeys(measure, CAPITAL_MEASURE_KEYS, label);
  nonEmptyString(measure.input_id, `${label}.input_id`);
  decimal(measure.value, `${label}.value`);
  nonEmptyString(measure.unit, `${label}.unit`);
  timestamp(measure.effective_at, `${label}.effective_at`);
  if (Date.parse(measure.effective_at as string) > Date.parse(cutoff)) {
    throw new TypeError(`${label} effective time occurs after cutoff`);
  }
  oneOf(
    measure.calculation_method,
    ["reported", "calculated"],
    `${label}.calculation_method`,
  );
  stringArray(measure.input_ids, `${label}.input_ids`);
  stringArray(
    measure.supporting_evidence_ids,
    `${label}.supporting_evidence_ids`,
  );
  oneOf(
    measure.freshness_state,
    ["current", "stale", "indeterminate"],
    `${label}.freshness_state`,
  );
  nonEmptyString(
    measure.freshness_reason_code,
    `${label}.freshness_reason_code`,
  );
  nonEmptyString(
    measure.freshness_policy_version,
    `${label}.freshness_policy_version`,
  );
  if (measure.calculation_method === "reported") {
    if (
      measure.formula !== null ||
      measure.calculation_id !== null ||
      (measure.input_ids as string[]).length !== 0
    ) {
      throw new TypeError(`invalid reported ${label}`);
    }
  } else {
    nonEmptyString(measure.formula, `${label}.formula`);
    nonEmptyString(measure.calculation_id, `${label}.calculation_id`);
    if ((measure.input_ids as string[]).length === 0) {
      throw new TypeError(`invalid calculated ${label}`);
    }
  }
  return measure as CapitalMeasure;
}

function parseCashTreatment(
  value: unknown,
  cutoff: string,
  includedCash: CapitalMeasure | null,
): CashTreatment {
  const treatment = record(value, "cash_treatment");
  exactKeys(treatment, CASH_TREATMENT_KEYS, "cash_treatment");
  const reportedCash = parseCapitalMeasure(
    treatment.reported_cash,
    "cash_treatment.reported_cash",
    cutoff,
  );
  const restrictedCash = parseCapitalMeasure(
    treatment.restricted_cash,
    "cash_treatment.restricted_cash",
    cutoff,
  );
  oneOf(
    treatment.restricted_cash_treatment,
    ["none", "included", "excluded"],
    "cash_treatment.restricted_cash_treatment",
  );
  if (includedCash === null) {
    throw new TypeError("cash treatment requires included cash");
  }
  if (
    reportedCash.unit !== includedCash.unit ||
    restrictedCash.unit !== includedCash.unit
  ) {
    throw new TypeError("cash treatment unit mismatch");
  }
  if (
    reportedCash.effective_at !== includedCash.effective_at ||
    restrictedCash.effective_at !== includedCash.effective_at
  ) {
    throw new TypeError("cash treatment effective time mismatch");
  }
  const restrictedComparison = compareDecimalValues(
    restrictedCash.value,
    reportedCash.value,
  );
  const treatmentName = treatment.restricted_cash_treatment as CashTreatment["restricted_cash_treatment"];
  const expectedIncludedCash =
    treatmentName === "excluded"
      ? subtractDecimalValues(reportedCash.value, restrictedCash.value)
      : reportedCash.value;
  if (
    restrictedComparison > 0 ||
    (treatmentName === "none" &&
      compareDecimalValues(restrictedCash.value, "0") !== 0) ||
    compareDecimalValues(includedCash.value, expectedIncludedCash) !== 0
  ) {
    throw new TypeError("restricted cash reconciliation mismatch");
  }
  return treatment as CashTreatment;
}

function parseDilutionInstrument(
  value: unknown,
  cutoff: string,
): DilutionInstrument {
  const instrument = record(value, "dilution instrument");
  exactKeys(instrument, DILUTION_INSTRUMENT_KEYS, "dilution instrument");
  nonEmptyString(instrument.instrument_id, "dilution instrument.instrument_id");
  oneOf(
    instrument.instrument_type,
    ["options", "warrants", "convertibles", "rsus", "preferred", "other"],
    "dilution instrument.instrument_type",
  );
  decimal(
    instrument.diluted_share_increment,
    "dilution instrument.diluted_share_increment",
  );
  timestamp(instrument.effective_at, "dilution instrument.effective_at");
  if (Date.parse(instrument.effective_at as string) > Date.parse(cutoff)) {
    throw new TypeError("dilution instrument occurs after cutoff");
  }
  stringArray(
    instrument.supporting_evidence_ids,
    "dilution instrument.supporting_evidence_ids",
  );
  return instrument as DilutionInstrument;
}

function parseDerivedValuation(
  value: unknown,
  label: string,
): DerivedValuation {
  const derived = record(value, label);
  exactKeys(derived, DERIVED_VALUATION_KEYS, label);
  decimal(derived.value, `${label}.value`);
  nonEmptyString(derived.unit, `${label}.unit`);
  nonEmptyString(derived.formula, `${label}.formula`);
  nonEmptyString(derived.formula_version, `${label}.formula_version`);
  stringArray(derived.input_ids, `${label}.input_ids`);
  if ((derived.input_ids as string[]).length === 0) {
    throw new TypeError(`invalid ${label}.input_ids`);
  }
  nonEmptyString(derived.calculation_id, `${label}.calculation_id`);
  stringArray(
    derived.supporting_evidence_ids,
    `${label}.supporting_evidence_ids`,
  );
  return derived as DerivedValuation;
}

function parseSourceReference(value: unknown): ValuationSourceReference {
  const source = record(value, "source reference");
  exactKeys(source, SOURCE_REFERENCE_KEYS, "source reference");
  nonEmptyString(source.source_reference_id, "source_reference_id");
  oneOf(
    source.source_type,
    ["licensed_market_data", "primary_filing"],
    "source_type",
  );
  nonEmptyString(source.provider, "source provider");
  nonEmptyString(source.locator, "source locator");
  nullableTimestamp(source.published_at, "source published_at");
  timestamp(source.retrieved_at, "source retrieved_at");
  nullableTimestamp(source.effective_at, "source effective_at");
  return source as ValuationSourceReference;
}

function parseCorporateAction(
  value: unknown,
): CorporateActionReconciliation {
  const action = record(value, "corporate_action_reconciliation");
  exactKeys(action, CORPORATE_ACTION_KEYS, "corporate_action_reconciliation");
  oneOf(
    action.event_type,
    [
      "none",
      "stock_split",
      "reverse_split",
      "merger",
      "conversion",
      "ticker_change",
      "exchange_change",
      "spin_off",
      "recapitalization",
      "share_class_conversion",
      "other",
    ],
    "corporate_action_reconciliation.event_type",
  );
  nullableTimestamp(action.effective_at, "corporate action effective_at");
  oneOf(
    action.price_adjustment_status,
    ["unadjusted", "adjusted", "not_applicable", "indeterminate"],
    "corporate action price_adjustment_status",
  );
  oneOf(
    action.share_count_adjustment_status,
    ["adjusted", "unadjusted", "not_applicable", "indeterminate"],
    "corporate action share_count_adjustment_status",
  );
  oneOf(
    action.reconciliation_result,
    ["reconciled", "not_required", "unresolved", "mismatch"],
    "corporate action reconciliation_result",
  );
  if (action.event_type === "none") {
    if (
      action.event_id !== null ||
      action.effective_at !== null ||
      action.reconciliation_result !== "not_required"
    ) {
      throw new TypeError("invalid no-action reconciliation");
    }
  } else {
    nonEmptyString(action.event_id, "corporate action event_id");
    timestamp(action.effective_at, "corporate action effective_at");
    if (action.reconciliation_result === "not_required") {
      throw new TypeError("invalid corporate action reconciliation");
    }
  }
  return action as CorporateActionReconciliation;
}

function parseMateriality(
  value: unknown,
  cutoff: string,
  closeTimestamp: string | null,
  policyVersion: string,
  evidenceIds: ReadonlySet<string>,
): MarketMateriality {
  const item = record(value, "evidence materiality");
  exactKeys(item, MARKET_MATERIALITY_KEYS, "evidence materiality");
  nonEmptyString(item.evidence_id, "materiality evidence_id");
  if (!evidenceIds.has(item.evidence_id as string)) {
    throw new TypeError("unresolved materiality evidence");
  }
  nullableTimestamp(item.publication_at, "materiality publication_at");
  oneOf(
    item.timing_state,
    [
      "before_or_at_close",
      "after_close_before_or_at_cutoff",
      "indeterminate",
    ],
    "materiality timing_state",
  );
  oneOf(
    item.market_materiality,
    ["material", "non_material", "indeterminate"],
    "market_materiality",
  );
  nonEmptyString(item.materiality_reason_code, "materiality_reason_code");
  if (item.materiality_policy_version !== policyVersion) {
    throw new TypeError("materiality policy mismatch");
  }
  if (!Array.isArray(item.affected_domains)) {
    throw new TypeError("invalid affected_domains");
  }
  for (const domain of item.affected_domains) {
    oneOf(
      domain,
      [
        "catalyst",
        "clinical",
        "regulatory",
        "financing",
        "dilution",
        "valuation",
        "management",
        "commercial",
      ],
      "affected domain",
    );
  }
  uniqueStrings(item.affected_domains as string[], "affected domain");
  if (item.publication_at === null || closeTimestamp === null) {
    if (item.timing_state !== "indeterminate") {
      throw new TypeError("ambiguous publication time must be indeterminate");
    }
  } else {
    const published = Date.parse(item.publication_at as string);
    if (published > Date.parse(cutoff)) {
      throw new TypeError("materiality evidence occurs after cutoff");
    }
    const expectedTiming =
      published <= Date.parse(closeTimestamp)
        ? "before_or_at_close"
        : "after_close_before_or_at_cutoff";
    if (item.timing_state !== expectedTiming) {
      throw new TypeError("materiality timing mismatch");
    }
  }
  return item as MarketMateriality;
}

export type ParsedValuationPriceContext = {
  input_id: string;
  timestamp: string;
  market_status: "closed" | "halted";
  corporate_action_adjustment_status: "unadjusted" | "indeterminate";
  provider_source_reference_id: string;
};

export function validateValuationSnapshotStructure(
  snapshot: Record<string, unknown>,
  price: ParsedValuationPriceContext | null,
  sourceReferenceIds: string[],
): void {
  for (const key of [
    "id",
    "operator_id",
    "research_run_id",
    "evidence_bundle_id",
    "security_id",
  ] as const) {
    uuid(snapshot[key], key);
  }
  sha256(snapshot.evidence_bundle_hash, "evidence_bundle_hash");
  timestamp(snapshot.as_of_cutoff, "as_of_cutoff");
  oneOf(snapshot.snapshot_status, ["valid", "invalid"], "snapshot_status");
  stringArray(snapshot.invalid_reason_codes, "invalid_reason_codes");
  if (typeof snapshot.currency !== "string" || !/^[A-Z]{3}$/.test(snapshot.currency)) {
    throw new TypeError("invalid currency");
  }
  const measures = [
    "basic_shares_outstanding",
    "fully_diluted_shares",
    "cash",
    "debt",
    "other_included_claims",
  ] as const;
  const parsedMeasures = new Map<string, CapitalMeasure>();
  for (const label of measures) {
    if (snapshot[label] !== null) {
      parsedMeasures.set(
        label,
        parseCapitalMeasure(
          snapshot[label],
          label,
          snapshot.as_of_cutoff as string,
        ),
      );
    }
  }
  const cashTreatment =
    snapshot.cash_treatment === null
      ? null
      : parseCashTreatment(
          snapshot.cash_treatment,
          snapshot.as_of_cutoff as string,
          parsedMeasures.get("cash") ?? null,
        );
  if (!Array.isArray(snapshot.dilution_instruments)) {
    throw new TypeError("invalid dilution_instruments");
  }
  const dilution = snapshot.dilution_instruments.map((item) =>
    parseDilutionInstrument(item, snapshot.as_of_cutoff as string),
  );
  const marketCapitalization =
    snapshot.market_capitalization === null
      ? null
      : parseDerivedValuation(
          snapshot.market_capitalization,
          "market_capitalization",
        );
  const enterpriseValue =
    snapshot.enterprise_value === null
      ? null
      : parseDerivedValuation(snapshot.enterprise_value, "enterprise_value");
  stringArray(snapshot.evidence_ids, "evidence_ids");
  stringArray(snapshot.calculation_ids, "calculation_ids");
  uniqueStrings(snapshot.evidence_ids as string[], "evidence_ids");
  uniqueStrings(snapshot.calculation_ids as string[], "calculation_ids");
  uniqueStrings(sourceReferenceIds, "source_reference_id");
  if (
    price !== null &&
    !sourceReferenceIds.includes(price.provider_source_reference_id)
  ) {
    throw new TypeError("unresolved price source reference");
  }
  const inputIds = [
    ...(price === null ? [] : [price.input_id]),
    ...[...parsedMeasures.values()].map((measure) => measure.input_id),
    ...(cashTreatment === null
      ? []
      : [
          cashTreatment.reported_cash.input_id,
          cashTreatment.restricted_cash.input_id,
        ]),
    ...dilution.map((instrument) => instrument.instrument_id),
  ];
  uniqueStrings(inputIds, "valuation input ID");
  const calculationIds = [
    ...[...parsedMeasures.values()]
      .map((measure) => measure.calculation_id)
      .filter((id): id is string => id !== null),
    ...(cashTreatment === null
      ? []
      : [
          cashTreatment.reported_cash.calculation_id,
          cashTreatment.restricted_cash.calculation_id,
        ].filter((id): id is string => id !== null)),
    ...(marketCapitalization === null
      ? []
      : [marketCapitalization.calculation_id]),
    ...(enterpriseValue === null ? [] : [enterpriseValue.calculation_id]),
  ];
  uniqueStrings(calculationIds, "calculation result ID");
  const declaredCalculations = snapshot.calculation_ids as string[];
  if (
    declaredCalculations.length !== calculationIds.length ||
    calculationIds.some((id) => !declaredCalculations.includes(id))
  ) {
    throw new TypeError("calculation_ids do not resolve exactly");
  }
  const resolvableInputs = new Set([...inputIds, ...calculationIds]);
  for (const calculation of [
    ...[...parsedMeasures.values()].filter(
      (measure) => measure.calculation_method === "calculated",
    ),
    ...(cashTreatment === null
      ? []
      : [
          cashTreatment.reported_cash,
          cashTreatment.restricted_cash,
        ].filter((measure) => measure.calculation_method === "calculated")),
    ...(marketCapitalization === null ? [] : [marketCapitalization]),
    ...(enterpriseValue === null ? [] : [enterpriseValue]),
  ]) {
    if (calculation.input_ids.some((id) => !resolvableInputs.has(id))) {
      throw new TypeError("unresolved calculation input");
    }
  }
  const declaredEvidence = new Set(snapshot.evidence_ids as string[]);
  for (const item of [
    ...parsedMeasures.values(),
    ...(cashTreatment === null
      ? []
      : [cashTreatment.reported_cash, cashTreatment.restricted_cash]),
    ...dilution,
    ...(marketCapitalization === null ? [] : [marketCapitalization]),
    ...(enterpriseValue === null ? [] : [enterpriseValue]),
  ]) {
    if (item.supporting_evidence_ids.some((id) => !declaredEvidence.has(id))) {
      throw new TypeError("unresolved supporting evidence");
    }
  }
  const action = parseCorporateAction(snapshot.corporate_action_reconciliation);
  nonEmptyString(
    snapshot.price_basis_policy_version,
    "price_basis_policy_version",
  );
  nonEmptyString(snapshot.freshness_policy_version, "freshness_policy_version");
  nonEmptyString(
    snapshot.materiality_policy_version,
    "materiality_policy_version",
  );
  if (!Array.isArray(snapshot.evidence_materiality)) {
    throw new TypeError("invalid evidence_materiality");
  }
  const materiality = snapshot.evidence_materiality.map((item) =>
    parseMateriality(
      item,
      snapshot.as_of_cutoff as string,
      price?.timestamp ?? null,
      snapshot.materiality_policy_version as string,
      declaredEvidence,
    ),
  );
  const materialityIds = materiality.map((item) => item.evidence_id);
  uniqueStrings(materialityIds, "materiality evidence_id");
  if (
    materialityIds.length !== declaredEvidence.size ||
    [...declaredEvidence].some((id) => !materialityIds.includes(id))
  ) {
    throw new TypeError("evidence materiality does not cover evidence exactly");
  }
  oneOf(
    snapshot.price_information_state,
    ["aligned", "pre_material_evidence", "indeterminate"],
    "price_information_state",
  );
  if (typeof snapshot.market_relative_analysis_permitted !== "boolean") {
    throw new TypeError("invalid market_relative_analysis_permitted");
  }
  const hasIndeterminate = materiality.some(
    (item) =>
      item.timing_state === "indeterminate" ||
      item.market_materiality === "indeterminate",
  );
  const hasPostCloseMaterial = materiality.some(
    (item) =>
      item.timing_state === "after_close_before_or_at_cutoff" &&
      item.market_materiality === "material",
  );
  const expectedInformationState: PriceInformationState = hasIndeterminate
    ? "indeterminate"
    : hasPostCloseMaterial
      ? "pre_material_evidence"
      : "aligned";
  if (snapshot.price_information_state !== expectedInformationState) {
    throw new TypeError("price information state mismatch");
  }
  const reasons = snapshot.invalid_reason_codes as string[];
  if (snapshot.snapshot_status === "valid") {
    if (reasons.length !== 0) {
      throw new TypeError("valid snapshot has invalid reasons");
    }
    if (
      price === null ||
      parsedMeasures.size !== measures.length ||
      cashTreatment === null ||
      marketCapitalization === null ||
      enterpriseValue === null ||
      sourceReferenceIds.length === 0 ||
      [...parsedMeasures.values()].some(
        (measure) =>
          measure.freshness_state !== "current" ||
          measure.freshness_policy_version !==
            snapshot.freshness_policy_version,
      ) ||
      [cashTreatment.reported_cash, cashTreatment.restricted_cash].some(
        (measure) =>
          measure.freshness_state !== "current" ||
          measure.freshness_policy_version !==
            snapshot.freshness_policy_version,
      ) ||
      price.market_status !== "closed" ||
      price.corporate_action_adjustment_status !== "unadjusted" ||
      !["reconciled", "not_required"].includes(action.reconciliation_result)
    ) {
      throw new TypeError("invalid inputs for valid snapshot");
    }
  } else if (reasons.length === 0) {
    throw new TypeError("invalid snapshot requires reason");
  }
  const shouldPermitMarketRelative =
    snapshot.snapshot_status === "valid" &&
    snapshot.price_information_state === "aligned" &&
    ["reconciled", "not_required"].includes(action.reconciliation_result);
  if (
    snapshot.market_relative_analysis_permitted !== shouldPermitMarketRelative
  ) {
    throw new TypeError("market-relative analysis permission mismatch");
  }
  timestamp(snapshot.created_at, "created_at");
  if (price !== null) {
    if (
      snapshot.snapshot_status === "valid" &&
      (price?.market_status !== "closed" ||
        price.corporate_action_adjustment_status !== "unadjusted")
    ) {
      throw new TypeError("invalid official close for valid snapshot");
    }
  }
}

export function parseValuationSnapshot(value: unknown): ValuationSnapshot {
  const snapshot = record(value, "Valuation Snapshot");
  exactKeys(snapshot, SNAPSHOT_KEYS, "Valuation Snapshot");
  oneOf(
    snapshot.contract_version,
    ["valuation_snapshot.v1"],
    "contract_version",
  );
  const priceBasis =
    snapshot.price_basis === null
      ? null
      : parsePriceBasis(snapshot.price_basis, snapshot.as_of_cutoff as string);
  if (!Array.isArray(snapshot.source_references)) {
    throw new TypeError("invalid source_references");
  }
  const sources = snapshot.source_references.map(parseSourceReference);
  validateValuationSnapshotStructure(
    snapshot,
    priceBasis === null
      ? null
      : {
          input_id: priceBasis.input_id,
          timestamp: priceBasis.official_close_timestamp,
          market_status: priceBasis.market_status,
          corporate_action_adjustment_status:
            priceBasis.corporate_action_adjustment_status,
          provider_source_reference_id:
            priceBasis.provider_source_reference_id,
        },
    sources.map((source) => source.source_reference_id),
  );
  return snapshot as ValuationSnapshot;
}
