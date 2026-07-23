import type { EligibilityResult, SecurityIdentity } from "./research-run.ts";

export type EvidenceSourceClass =
  | "sec"
  | "issuer"
  | "clinical"
  | "regulatory"
  | "financing";

export type EvidenceItemKind = "passage" | "metric" | "catalyst" | "risk";
export type FreshnessState = "current" | "stale" | "indeterminate";

export type EvidenceManifestEntry = {
  ordinal: number;
  item_id: string;
  item_version_id: string;
  item_kind: EvidenceItemKind;
  source_class: EvidenceSourceClass;
  source_locator: string;
  locator: string;
  content_sha256: string;
  published_at: string | null;
  retrieved_at: string;
  effective_at: string | null;
  filing_period_start: string | null;
  filing_period_end: string | null;
  freshness_state: FreshnessState;
  freshness_reason_code: string;
  freshness_policy_version: string;
};

export type VerifiedMetricSnapshot = {
  id: string;
  metric_key: string;
  value: string;
  unit: string;
  period_start: string | null;
  period_end: string | null;
  calculation_method: "reported" | "calculated";
  formula: string | null;
  supporting_evidence_ids: string[];
};

export type CatalystSnapshot = {
  id: string;
  program: string;
  event: string;
  basis: "clinical" | "regulatory";
  status: string;
  window_start: string;
  window_end: string;
  supporting_evidence_ids: string[];
};

export type RiskSnapshot = {
  id: string;
  title: string;
  risk_type: string;
  severity: string;
  status: string;
  supporting_evidence_ids: string[];
};

export type EvidenceGap = {
  gap_id: string;
  requirement_id: string;
  source_class: EvidenceSourceClass;
  reason_code: string;
  explanation: string;
};

export type EvidenceBundle = {
  contract_version: "evidence_bundle.v1";
  id: string;
  operator_id: string;
  research_run_id: string;
  security_id: string;
  security_identity: SecurityIdentity;
  as_of_cutoff: string;
  bundle_hash: string;
  manifest: EvidenceManifestEntry[];
  verified_metrics: VerifiedMetricSnapshot[];
  catalysts: CatalystSnapshot[];
  risks: RiskSnapshot[];
  eligibility: EligibilityResult;
  evidence_policy_version: string;
  freshness_policy_version: string;
  grader_ready: boolean;
  gaps: EvidenceGap[];
  created_at: string;
};

const BUNDLE_KEYS = [
  "contract_version",
  "id",
  "operator_id",
  "research_run_id",
  "security_id",
  "security_identity",
  "as_of_cutoff",
  "bundle_hash",
  "manifest",
  "verified_metrics",
  "catalysts",
  "risks",
  "eligibility",
  "evidence_policy_version",
  "freshness_policy_version",
  "grader_ready",
  "gaps",
  "created_at",
] as const;

const MANIFEST_KEYS = [
  "ordinal",
  "item_id",
  "item_version_id",
  "item_kind",
  "source_class",
  "source_locator",
  "locator",
  "content_sha256",
  "published_at",
  "retrieved_at",
  "effective_at",
  "filing_period_start",
  "filing_period_end",
  "freshness_state",
  "freshness_reason_code",
  "freshness_policy_version",
] as const;

const SOURCE_CLASSES = [
  "sec",
  "issuer",
  "clinical",
  "regulatory",
  "financing",
] as const;
const ITEM_KINDS = ["passage", "metric", "catalyst", "risk"] as const;
const FRESHNESS_STATES = ["current", "stale", "indeterminate"] as const;
const METRIC_KEYS = [
  "id",
  "metric_key",
  "value",
  "unit",
  "period_start",
  "period_end",
  "calculation_method",
  "formula",
  "supporting_evidence_ids",
] as const;
const CATALYST_KEYS = [
  "id",
  "program",
  "event",
  "basis",
  "status",
  "window_start",
  "window_end",
  "supporting_evidence_ids",
] as const;
const RISK_KEYS = [
  "id",
  "title",
  "risk_type",
  "severity",
  "status",
  "supporting_evidence_ids",
] as const;
const GAP_KEYS = [
  "gap_id",
  "requirement_id",
  "source_class",
  "reason_code",
  "explanation",
] as const;
const ELIGIBILITY_KEYS = [
  "policy_version",
  "eligible",
  "checks",
  "evaluated_at",
] as const;
const ELIGIBILITY_CHECK_KEYS = [
  "rule_id",
  "rule_version",
  "passed",
  "evidence_reference",
  "reason_code",
  "explanation",
  "evaluated_at",
] as const;
const ELIGIBILITY_RULE_IDS = [
  "security_identity_verified",
  "us_listing",
  "cik_match",
  "common_equity",
  "operating_company",
  "therapeutics_classification",
  "active_therapeutic_program",
  "defined_clinical_or_regulatory_catalyst",
  "required_primary_source_coverage",
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) throw new TypeError(`invalid ${label}`);
  return value;
}

function exactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
  label: string,
) {
  const actual = Object.keys(value).sort();
  const keys = [...expected].sort();
  if (
    actual.length !== keys.length ||
    actual.some((key, index) => key !== keys[index])
  ) {
    throw new TypeError(`invalid ${label} fields`);
  }
}

function nonEmptyString(value: unknown, label: string) {
  if (typeof value !== "string" || value.length === 0) {
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

function timestamp(value: unknown, label: string) {
  nonEmptyString(value, label);
  if (
    !/(?:z|[+-]\d{2}:\d{2})$/i.test(value as string) ||
    Number.isNaN(Date.parse(value as string))
  ) {
    throw new TypeError(`invalid ${label}`);
  }
}

function nullableTimestamp(value: unknown, label: string) {
  if (value !== null) timestamp(value, label);
}

function nullableDate(value: unknown, label: string) {
  if (value !== null && (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value))) {
    throw new TypeError(`invalid ${label}`);
  }
}

function stringArray(value: unknown, label: string) {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.length === 0)) {
    throw new TypeError(`invalid ${label}`);
  }
}

function requireResolvedEvidence(
  value: unknown,
  passageIds: ReadonlySet<string>,
  label: string,
) {
  stringArray(value, label);
  if (
    (value as string[]).length === 0 ||
    (value as string[]).some((id) => !passageIds.has(id))
  ) {
    throw new TypeError(`unresolved ${label}`);
  }
}

function parseSecurityIdentity(
  value: unknown,
  securityId: unknown,
): SecurityIdentity {
  const identity = record(value, "bundle security identity");
  exactKeys(
    identity,
    ["id", "cik", "issuer_name", "symbol", "primary_listing_exchange"],
    "bundle security identity",
  );
  uuid(identity.id, "bundle security identity id");
  if (identity.id !== securityId) {
    throw new TypeError("inconsistent bundle security identity");
  }
  for (const key of ["cik", "issuer_name", "symbol", "primary_listing_exchange"] as const) {
    nonEmptyString(identity[key], `bundle security ${key}`);
  }
  return identity as SecurityIdentity;
}

function parseManifest(
  value: unknown,
  cutoff: string,
  freshnessPolicyVersion: string,
): EvidenceManifestEntry[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new TypeError("invalid evidence manifest");
  }
  const entries = value.map((raw, index) => {
    const item = record(raw, "manifest entry");
    exactKeys(item, MANIFEST_KEYS, "manifest entry");
    if (item.ordinal !== index + 1) {
      throw new TypeError("non-contiguous evidence manifest ordinals");
    }
    uuid(item.item_id, "manifest item id");
    uuid(item.item_version_id, "manifest item version id");
    if (!ITEM_KINDS.includes(item.item_kind as EvidenceItemKind)) {
      throw new TypeError("invalid manifest item kind");
    }
    if (!SOURCE_CLASSES.includes(item.source_class as EvidenceSourceClass)) {
      throw new TypeError("invalid manifest source class");
    }
    nonEmptyString(item.source_locator, "manifest source locator");
    try {
      const sourceUrl = new URL(item.source_locator as string);
      if (sourceUrl.protocol !== "https:") {
        throw new TypeError("manifest source locator must use HTTPS");
      }
    } catch (error) {
      if (error instanceof TypeError && error.message === "manifest source locator must use HTTPS") {
        throw error;
      }
      throw new TypeError("invalid manifest source locator");
    }
    nonEmptyString(item.locator, "manifest locator");
    sha256(item.content_sha256, "manifest content hash");
    nullableTimestamp(item.published_at, "manifest publication timestamp");
    timestamp(item.retrieved_at, "manifest retrieval timestamp");
    nullableTimestamp(item.effective_at, "manifest effective timestamp");
    nullableDate(item.filing_period_start, "manifest filing period start");
    nullableDate(item.filing_period_end, "manifest filing period end");
    if (!FRESHNESS_STATES.includes(item.freshness_state as FreshnessState)) {
      throw new TypeError("invalid manifest freshness state");
    }
    nonEmptyString(item.freshness_reason_code, "manifest freshness reason");
    nonEmptyString(item.freshness_policy_version, "manifest freshness policy");
    if (item.freshness_policy_version !== freshnessPolicyVersion) {
      throw new TypeError("inconsistent manifest freshness policy");
    }
    if (
      (typeof item.published_at === "string" &&
        Date.parse(item.published_at) > Date.parse(cutoff)) ||
      (typeof item.effective_at === "string" &&
        Date.parse(item.effective_at) > Date.parse(cutoff))
    ) {
      throw new TypeError("manifest evidence is after bundle cutoff");
    }
    if (
      typeof item.filing_period_start === "string" &&
      typeof item.filing_period_end === "string" &&
      item.filing_period_start > item.filing_period_end
    ) {
      throw new TypeError("invalid manifest filing period");
    }
    return item as EvidenceManifestEntry;
  });

  const itemIds = entries.map((item) => item.item_id);
  const versionIds = entries.map((item) => item.item_version_id);
  if (
    new Set(itemIds).size !== itemIds.length ||
    new Set(versionIds).size !== versionIds.length
  ) {
    throw new TypeError("duplicate evidence manifest identity");
  }
  const sourceRank = new Map(SOURCE_CLASSES.map((value, index) => [value, index]));
  const kindRank = new Map(ITEM_KINDS.map((value, index) => [value, index]));
  const canonical = [...entries].sort((left, right) => {
    const sourceDifference =
      sourceRank.get(left.source_class)! - sourceRank.get(right.source_class)!;
    if (sourceDifference !== 0) return sourceDifference;
    const kindDifference =
      kindRank.get(left.item_kind)! - kindRank.get(right.item_kind)!;
    if (kindDifference !== 0) return kindDifference;
    return left.item_id.localeCompare(right.item_id);
  });
  if (entries.some((item, index) => item !== canonical[index])) {
    throw new TypeError("evidence manifest is not canonically ordered");
  }
  return entries;
}

function parseEligibility(value: unknown): EligibilityResult {
  const eligibility = record(value, "bundle eligibility");
  exactKeys(eligibility, ELIGIBILITY_KEYS, "bundle eligibility");
  nonEmptyString(eligibility.policy_version, "bundle eligibility policy");
  if (typeof eligibility.eligible !== "boolean" || !Array.isArray(eligibility.checks)) {
    throw new TypeError("invalid bundle eligibility result");
  }
  timestamp(eligibility.evaluated_at, "bundle eligibility timestamp");
  if (eligibility.checks.length !== ELIGIBILITY_RULE_IDS.length) {
    throw new TypeError("invalid bundle eligibility rule count");
  }
  for (const [index, raw] of eligibility.checks.entries()) {
    const check = record(raw, "bundle eligibility check");
    exactKeys(check, ELIGIBILITY_CHECK_KEYS, "bundle eligibility check");
    const expectedRuleId = ELIGIBILITY_RULE_IDS[index];
    if (
      check.rule_id !== expectedRuleId ||
      check.rule_version !== `${expectedRuleId}.v1` ||
      typeof check.passed !== "boolean" ||
      (check.evidence_reference !== null &&
        typeof check.evidence_reference !== "string")
    ) {
      throw new TypeError("invalid bundle eligibility check");
    }
    nonEmptyString(check.reason_code, "bundle eligibility reason");
    nonEmptyString(check.explanation, "bundle eligibility explanation");
    timestamp(check.evaluated_at, "bundle eligibility check timestamp");
  }
  if (
    eligibility.eligible !==
    eligibility.checks.every(
      (check) => record(check, "bundle eligibility check").passed === true,
    )
  ) {
    throw new TypeError("inconsistent bundle eligibility outcome");
  }
  return eligibility as unknown as EligibilityResult;
}

function parseGaps(value: unknown): EvidenceGap[] {
  if (!Array.isArray(value)) throw new TypeError("invalid evidence gaps");
  const gaps = value.map((raw) => {
    const gap = record(raw, "evidence gap");
    exactKeys(gap, GAP_KEYS, "evidence gap");
    for (const key of [
      "gap_id",
      "requirement_id",
      "reason_code",
      "explanation",
    ] as const) {
      nonEmptyString(gap[key], `evidence gap ${key}`);
    }
    if (!SOURCE_CLASSES.includes(gap.source_class as EvidenceSourceClass)) {
      throw new TypeError("invalid evidence gap source class");
    }
    return gap as EvidenceGap;
  });
  if (new Set(gaps.map((gap) => gap.gap_id)).size !== gaps.length) {
    throw new TypeError("duplicate evidence gap identity");
  }
  const sourceRank = new Map(SOURCE_CLASSES.map((value, index) => [value, index]));
  const canonical = [...gaps].sort((left, right) => {
    const difference =
      sourceRank.get(left.source_class)! - sourceRank.get(right.source_class)!;
    return difference || left.requirement_id.localeCompare(right.requirement_id);
  });
  if (gaps.some((gap, index) => gap !== canonical[index])) {
    throw new TypeError("evidence gaps are not canonically ordered");
  }
  return gaps;
}

function parseMetrics(
  value: unknown,
  manifestKinds: ReadonlyMap<string, EvidenceItemKind>,
  passageIds: ReadonlySet<string>,
): VerifiedMetricSnapshot[] {
  if (!Array.isArray(value)) throw new TypeError("invalid verified metrics");
  return value.map((raw) => {
    const metric = record(raw, "verified metric");
    exactKeys(metric, METRIC_KEYS, "verified metric");
    uuid(metric.id, "verified metric id");
    if (manifestKinds.get(metric.id as string) !== "metric") {
      throw new TypeError("verified metric lacks matching manifest entry");
    }
    nonEmptyString(metric.metric_key, "verified metric key");
    if (
      typeof metric.value !== "string" ||
      !/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(metric.value)
    ) {
      throw new TypeError("verified metric value must be canonical decimal text");
    }
    nonEmptyString(metric.unit, "verified metric unit");
    nullableDate(metric.period_start, "verified metric period start");
    nullableDate(metric.period_end, "verified metric period end");
    if (!(["reported", "calculated"] as const).includes(metric.calculation_method as "reported" | "calculated")) {
      throw new TypeError("invalid verified metric calculation method");
    }
    if (metric.formula !== null && (typeof metric.formula !== "string" || metric.formula.length === 0)) {
      throw new TypeError("invalid verified metric formula");
    }
    if (metric.calculation_method === "calculated" && metric.formula === null) {
      throw new TypeError("calculated metric requires formula");
    }
    requireResolvedEvidence(
      metric.supporting_evidence_ids,
      passageIds,
      "verified metric evidence",
    );
    return metric as VerifiedMetricSnapshot;
  });
}

function parseCatalysts(
  value: unknown,
  manifestKinds: ReadonlyMap<string, EvidenceItemKind>,
  passageIds: ReadonlySet<string>,
): CatalystSnapshot[] {
  if (!Array.isArray(value)) throw new TypeError("invalid catalysts");
  return value.map((raw) => {
    const catalyst = record(raw, "catalyst snapshot");
    exactKeys(catalyst, CATALYST_KEYS, "catalyst snapshot");
    uuid(catalyst.id, "catalyst snapshot id");
    if (manifestKinds.get(catalyst.id as string) !== "catalyst") {
      throw new TypeError("catalyst lacks matching manifest entry");
    }
    for (const key of ["program", "event", "status"] as const) {
      nonEmptyString(catalyst[key], `catalyst ${key}`);
    }
    if (!(catalyst.basis === "clinical" || catalyst.basis === "regulatory")) {
      throw new TypeError("invalid catalyst basis");
    }
    nullableDate(catalyst.window_start, "catalyst window start");
    nullableDate(catalyst.window_end, "catalyst window end");
    if (
      typeof catalyst.window_start !== "string" ||
      typeof catalyst.window_end !== "string" ||
      catalyst.window_start > catalyst.window_end
    ) {
      throw new TypeError("invalid catalyst window");
    }
    requireResolvedEvidence(
      catalyst.supporting_evidence_ids,
      passageIds,
      "catalyst evidence",
    );
    return catalyst as CatalystSnapshot;
  });
}

function parseRisks(
  value: unknown,
  manifestKinds: ReadonlyMap<string, EvidenceItemKind>,
  passageIds: ReadonlySet<string>,
): RiskSnapshot[] {
  if (!Array.isArray(value)) throw new TypeError("invalid risks");
  return value.map((raw) => {
    const risk = record(raw, "risk snapshot");
    exactKeys(risk, RISK_KEYS, "risk snapshot");
    uuid(risk.id, "risk snapshot id");
    if (manifestKinds.get(risk.id as string) !== "risk") {
      throw new TypeError("risk lacks matching manifest entry");
    }
    for (const key of ["title", "risk_type", "severity", "status"] as const) {
      nonEmptyString(risk[key], `risk ${key}`);
    }
    requireResolvedEvidence(
      risk.supporting_evidence_ids,
      passageIds,
      "risk evidence",
    );
    return risk as RiskSnapshot;
  });
}

export function parseEvidenceBundle(value: unknown): EvidenceBundle {
  const bundle = record(value, "Evidence Bundle");
  exactKeys(bundle, BUNDLE_KEYS, "Evidence Bundle");
  if (bundle.contract_version !== "evidence_bundle.v1") {
    throw new TypeError("invalid Evidence Bundle contract version");
  }
  uuid(bundle.id, "bundle id");
  uuid(bundle.operator_id, "bundle operator id");
  uuid(bundle.research_run_id, "bundle research run id");
  uuid(bundle.security_id, "bundle security id");
  parseSecurityIdentity(bundle.security_identity, bundle.security_id);
  timestamp(bundle.as_of_cutoff, "bundle cutoff");
  timestamp(bundle.created_at, "bundle creation timestamp");
  sha256(bundle.bundle_hash, "bundle hash");
  nonEmptyString(bundle.evidence_policy_version, "bundle evidence policy");
  nonEmptyString(bundle.freshness_policy_version, "bundle freshness policy");
  const manifest = parseManifest(
    bundle.manifest,
    bundle.as_of_cutoff as string,
    bundle.freshness_policy_version as string,
  );
  const manifestKinds = new Map(
    manifest.map((item) => [item.item_id, item.item_kind]),
  );
  const passageIds = new Set(
    manifest
      .filter((item) => item.item_kind === "passage")
      .map((item) => item.item_id),
  );
  if (typeof bundle.grader_ready !== "boolean") {
    throw new TypeError("invalid Evidence Bundle collections");
  }
  parseMetrics(bundle.verified_metrics, manifestKinds, passageIds);
  parseCatalysts(bundle.catalysts, manifestKinds, passageIds);
  parseRisks(bundle.risks, manifestKinds, passageIds);
  const eligibility = parseEligibility(bundle.eligibility);
  const gaps = parseGaps(bundle.gaps);
  const coveredSourceClasses = new Set(
    manifest.map((item) => item.source_class),
  );
  if (
    bundle.grader_ready === true &&
    (!eligibility.eligible ||
      gaps.length !== 0 ||
      SOURCE_CLASSES.some((sourceClass) => !coveredSourceClasses.has(sourceClass)))
  ) {
    throw new TypeError("inconsistent grader-ready Evidence Bundle");
  }
  if (bundle.grader_ready === false && gaps.length === 0) {
    throw new TypeError("blocked Evidence Bundle requires evidence gaps");
  }
  return bundle as EvidenceBundle;
}
