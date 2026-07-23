import assert from "node:assert/strict";
import test from "node:test";

import { presentDashboardShell } from "./dashboard-shell.ts";

test("the dashboard shell presents research navigation and auditable information alignment", () => {
  const shell = presentDashboardShell({
    activeSection: "overview",
    evidenceBundleHash:
      "sha256:5ddf4ca08f45236f669806e323cc74482328479d9cb6d76ab75d551a6473bdf2",
    evidenceCutoff: "2026-07-20T20:00:00Z",
    marketPriceSession: "2026-07-20",
    priceInformationState: "aligned",
  });

  assert.deepEqual(
    shell.navigation.map(({ available, current, label }) => ({
      available,
      current,
      label,
    })),
    [
      { available: true, current: true, label: "Overview" },
      { available: true, current: false, label: "Evidence" },
      { available: false, current: false, label: "Committee" },
      { available: false, current: false, label: "Thesis" },
      { available: false, current: false, label: "Audit" },
    ],
  );
  assert.deepEqual(shell.informationAlignment, {
    fields: [
      { label: "Evidence cutoff", value: "20 Jul 2026, 20:00 UTC" },
      { label: "Market price session", value: "20 Jul 2026" },
      {
        label: "Evidence bundle",
        value:
          "sha256:5ddf4ca08f45236f669806e323cc74482328479d9cb6d76ab75d551a6473bdf2",
      },
    ],
    label: "Information alignment",
    state: {
      label: "Aligned",
      tone: "verified",
      value: "aligned",
    },
  });
});
