import assert from "node:assert/strict";
import test from "node:test";

import {
  selectHighestPriorityActiveRisk,
  selectRelevantCatalyst,
} from "./context-selection.ts";

const catalyst = {
  title: "Historical readout",
  status: "occurred" as const,
  window_start: "2025-06-01",
  window_end: "2025-06-30",
  locator: "historical",
  passage_text: "Historical evidence",
  passage_sha256: "a".repeat(64),
  source_title: "Issuer release",
  published_at: "2025-05-01T12:00:00Z",
  source_url: "https://example.com/historical",
  retrieved_at: "2025-05-01T13:00:00Z",
};

test("selects next relevant catalyst instead of oldest historical catalyst", () => {
  const selected = selectRelevantCatalyst(
    [
      catalyst,
      {
        ...catalyst,
        title: "Later pipeline update",
        status: "expected",
        window_start: "2026-12-01",
        window_end: "2026-12-31",
      },
      {
        ...catalyst,
        title: "Near-term clinical readout",
        status: "expected",
        window_start: "2026-09-01",
        window_end: "2026-09-30",
      },
    ],
    "2026-07-29",
  );

  assert.equal(selected?.title, "Near-term clinical readout");
});

test("uses immutable source identity to break exact catalyst priority ties", () => {
  const zeta = {
    ...catalyst,
    title: "Shared catalyst",
    status: "expected" as const,
    window_start: "2026-09-01",
    window_end: "2026-09-30",
    published_at: "2026-07-01T12:00:00Z",
    source_url: "https://example.com/zeta",
  };
  const alpha = {
    ...zeta,
    source_url: "https://example.com/alpha",
  };

  assert.equal(
    selectRelevantCatalyst([zeta, alpha], "2026-07-29")?.sourceUrl,
    "https://example.com/alpha",
  );
  assert.equal(
    selectRelevantCatalyst([alpha, zeta], "2026-07-29")?.sourceUrl,
    "https://example.com/alpha",
  );
});

const risk = {
  title: "Medium financing risk",
  risk_type: "financial" as const,
  severity: "medium" as const,
  status: "active" as const,
  locator: "risk",
  passage_text: "Risk evidence",
  passage_sha256: "b".repeat(64),
  source_title: "Issuer release",
  published_at: "2026-07-01T12:00:00Z",
  source_url: "https://example.com/risk",
  retrieved_at: "2026-07-01T13:00:00Z",
};

test("selects highest-severity active risk independent of database row order", () => {
  const high = {
    ...risk,
    title: "High clinical risk",
    risk_type: "clinical" as const,
    severity: "high" as const,
  };

  assert.equal(
    selectHighestPriorityActiveRisk([risk, high])?.title,
    "High clinical risk",
  );
  assert.equal(
    selectHighestPriorityActiveRisk([high, risk])?.title,
    "High clinical risk",
  );
});

test("selects newest evidence when active risk severity matches", () => {
  const older = {
    ...risk,
    title: "Older high risk",
    severity: "high" as const,
    published_at: "2026-05-01T12:00:00Z",
  };
  const newer = {
    ...older,
    title: "Updated high risk",
    published_at: "2026-07-01T12:00:00Z",
  };

  assert.equal(
    selectHighestPriorityActiveRisk([older, newer])?.title,
    "Updated high risk",
  );
  assert.equal(
    selectHighestPriorityActiveRisk([newer, older])?.title,
    "Updated high risk",
  );
});

test("uses stable identity fields when risk priority and evidence date match", () => {
  const beta = {
    ...risk,
    title: "Beta risk",
    severity: "high" as const,
  };
  const alpha = {
    ...beta,
    title: "Alpha risk",
  };

  assert.equal(
    selectHighestPriorityActiveRisk([beta, alpha])?.title,
    "Alpha risk",
  );
  assert.equal(
    selectHighestPriorityActiveRisk([alpha, beta])?.title,
    "Alpha risk",
  );
});

test("uses risk domain as deterministic tie-breaker for duplicate titles", () => {
  const regulatory = {
    ...risk,
    title: "Shared risk title",
    risk_type: "regulatory" as const,
    severity: "high" as const,
  };
  const clinical = {
    ...regulatory,
    risk_type: "clinical" as const,
  };

  assert.equal(
    selectHighestPriorityActiveRisk([regulatory, clinical])?.riskType,
    "clinical",
  );
  assert.equal(
    selectHighestPriorityActiveRisk([clinical, regulatory])?.riskType,
    "clinical",
  );
});

test("uses immutable source identity to break exact risk priority ties", () => {
  const zeta = {
    ...risk,
    title: "Shared risk",
    severity: "high" as const,
    source_url: "https://example.com/zeta-risk",
  };
  const alpha = {
    ...zeta,
    source_url: "https://example.com/alpha-risk",
  };

  assert.equal(
    selectHighestPriorityActiveRisk([zeta, alpha])?.sourceUrl,
    "https://example.com/alpha-risk",
  );
  assert.equal(
    selectHighestPriorityActiveRisk([alpha, zeta])?.sourceUrl,
    "https://example.com/alpha-risk",
  );
});
