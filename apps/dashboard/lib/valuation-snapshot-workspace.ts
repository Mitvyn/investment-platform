import type {
  CapitalMeasure,
  DerivedValuation,
  ResearchRun,
  ValuationSnapshot,
} from "@iros/types";

type StateVariant = "verified" | "attention" | "destructive";

function presentCapitalInput(
  label: string,
  measure: CapitalMeasure | null,
) {
  if (measure === null) return null;
  return {
    label,
    value: measure.value,
    unit: measure.unit,
    fields: [
      { label: "Input ID", value: measure.input_id },
      { label: "Effective", value: measure.effective_at },
      { label: "Method", value: measure.calculation_method },
      { label: "Formula", value: measure.formula ?? "Reported value" },
      {
        label: "Calculation ID",
        value: measure.calculation_id ?? "Not applicable",
      },
      { label: "Input IDs", value: measure.input_ids.join(", ") || "None" },
      {
        label: "Evidence IDs",
        value: measure.supporting_evidence_ids.join(", "),
      },
      { label: "Freshness", value: measure.freshness_state },
      { label: "Freshness reason", value: measure.freshness_reason_code },
      { label: "Freshness policy", value: measure.freshness_policy_version },
    ],
  };
}

function presentDerivedValue(
  label: string,
  value: DerivedValuation | null,
) {
  if (value === null) return null;
  return {
    label,
    value: `${value.value} ${value.unit}`,
    formula: value.formula,
    formulaVersion: value.formula_version,
    calculationId: value.calculation_id,
    inputIds: value.input_ids,
    evidenceIds: value.supporting_evidence_ids,
  };
}

function alignmentPresentation(snapshot: ValuationSnapshot): {
  label: string;
  variant: StateVariant;
  description: string;
} {
  if (snapshot.price_information_state === "aligned") {
    return {
      label: "Aligned",
      variant: "verified",
      description:
        "Official close reflects all market-material evidence in this Research Run.",
    };
  }
  if (snapshot.price_information_state === "pre_material_evidence") {
    return {
      label: "Price predates material evidence",
      variant: "attention",
      description:
        "Official close predates market-material evidence used by this Research Run.",
    };
  }
  return {
    label: "Indeterminate",
    variant: "attention",
    description:
      "Evidence timing or materiality cannot be aligned reliably to the official close.",
  };
}

function marketRelativePresentation(snapshot: ValuationSnapshot) {
  if (snapshot.market_relative_analysis_permitted) {
    return {
      label: "Market-relative analysis permitted" as const,
      variant: "verified" as const,
    };
  }
  return {
    label: "Market-relative analysis blocked" as const,
    variant:
      snapshot.snapshot_status === "invalid"
        ? ("destructive" as const)
        : ("attention" as const),
  };
}

export function presentValuationSnapshotWorkspace(
  run: ResearchRun,
  snapshot: ValuationSnapshot | null,
) {
  if (snapshot === null) {
    return {
      kind: "missing" as const,
      description:
        "This Research Run has no persisted point-in-time Valuation Snapshot yet.",
      status: { label: "Not materialized" as const, variant: "attention" as const },
    };
  }
  if (
    snapshot.operator_id !== run.operator_id ||
    snapshot.research_run_id !== run.id ||
    snapshot.security_id !== run.security_id ||
    snapshot.as_of_cutoff !== run.as_of_cutoff
  ) {
    throw new TypeError(
      "Valuation Snapshot is outside Research Run valuation boundary",
    );
  }

  const priceBasis = snapshot.price_basis;
  const capitalInputs = [
    presentCapitalInput("Basic shares", snapshot.basic_shares_outstanding),
    presentCapitalInput("Fully diluted shares", snapshot.fully_diluted_shares),
    presentCapitalInput("Cash", snapshot.cash),
    presentCapitalInput("Debt", snapshot.debt),
  ].filter((value) => value !== null);
  const derivedValues = [
    presentDerivedValue("Market capitalization", snapshot.market_capitalization),
    presentDerivedValue("Enterprise value", snapshot.enterprise_value),
  ].filter((value) => value !== null);

  return {
    kind: "ready" as const,
    snapshot,
    status:
      snapshot.snapshot_status === "valid"
        ? { label: "Valid snapshot" as const, variant: "verified" as const }
        : { label: "Invalid snapshot" as const, variant: "destructive" as const },
    alignment: alignmentPresentation(snapshot),
    marketRelativeAnalysis: marketRelativePresentation(snapshot),
    summary: [
      { label: "Snapshot ID", value: snapshot.id },
      { label: "Evidence Bundle ID", value: snapshot.evidence_bundle_id },
      { label: "Evidence Bundle hash", value: snapshot.evidence_bundle_hash },
      { label: "Cutoff", value: snapshot.as_of_cutoff },
      { label: "Currency", value: snapshot.currency },
      { label: "Price-basis policy", value: snapshot.price_basis_policy_version },
      { label: "Freshness policy", value: snapshot.freshness_policy_version },
      { label: "Materiality policy", value: snapshot.materiality_policy_version },
      { label: "Created", value: snapshot.created_at },
    ],
    priceBasis:
      priceBasis === null
        ? null
        : {
            headline: `${snapshot.currency} ${priceBasis.share_price}`,
            fields: [
              { label: "Price type", value: priceBasis.price_type },
              { label: "Session", value: priceBasis.session_date },
              { label: "Session type", value: priceBasis.session_type },
              { label: "Exchange", value: priceBasis.primary_listing_exchange },
              { label: "Official close", value: priceBasis.official_close_timestamp },
              { label: "Market status", value: priceBasis.market_status },
              {
                label: "Price adjustment",
                value: priceBasis.corporate_action_adjustment_status,
              },
              { label: "Calendar", value: priceBasis.market_calendar_version },
              { label: "Input ID", value: priceBasis.input_id },
              {
                label: "Source reference",
                value: priceBasis.provider_source_reference_id,
              },
            ],
          },
    capitalInputs,
    dilutionInstruments: snapshot.dilution_instruments.map((instrument) => ({
      id: instrument.instrument_id,
      type: instrument.instrument_type,
      increment: instrument.diluted_share_increment,
      effective: instrument.effective_at,
      evidenceIds: instrument.supporting_evidence_ids,
    })),
    derivedValues,
    corporateAction: {
      event: snapshot.corporate_action_reconciliation.event_type,
      eventId:
        snapshot.corporate_action_reconciliation.event_id ?? "Not applicable",
      effective:
        snapshot.corporate_action_reconciliation.effective_at ?? "Not applicable",
      priceAdjustment:
        snapshot.corporate_action_reconciliation.price_adjustment_status,
      shareCountAdjustment:
        snapshot.corporate_action_reconciliation.share_count_adjustment_status,
      result: snapshot.corporate_action_reconciliation.reconciliation_result,
    },
    invalidReasons: snapshot.invalid_reason_codes.map((code) => ({
      code,
      label: code.replaceAll("_", " "),
    })),
    sourceReferences: snapshot.source_references.map((source) => ({
      id: source.source_reference_id,
      type: source.source_type,
      provider: source.provider,
      locator: source.locator,
      published: source.published_at ?? "Not available",
      retrieved: source.retrieved_at,
      effective: source.effective_at ?? "Not applicable",
    })),
    materiality: snapshot.evidence_materiality.map((item) => ({
      evidenceId: item.evidence_id,
      published: item.publication_at ?? "Not available",
      timing: item.timing_state,
      materiality: item.market_materiality,
      reason: item.materiality_reason_code,
      policy: item.materiality_policy_version,
      domains: item.affected_domains,
    })),
    evidenceIds: snapshot.evidence_ids,
    calculationIds: snapshot.calculation_ids,
  };
}
