import assert from "node:assert/strict";
import test from "node:test";

import {
  furthestAvailableStage,
  parseDashboardSection,
  parseResearchStage,
  presentDashboardShell,
  presentResearchStages,
  type ResearchRunFacts,
} from "./dashboard-shell.ts";

test("the dashboard shell presents product features and auditable information alignment", () => {
  const shell = presentDashboardShell({
    activeSection: "dashboard",
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
      { available: true, current: true, label: "Dashboard" },
      { available: true, current: false, label: "Research" },
      { available: false, current: false, label: "Quant" },
      { available: true, current: false, label: "Settings" },
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

test("feature parsing defaults to Dashboard and accepts only real features", () => {
  assert.equal(parseDashboardSection(undefined), "dashboard");
  assert.equal(parseDashboardSection("research"), "research");
  assert.equal(parseDashboardSection("quant"), "quant");
  assert.equal(parseDashboardSection("settings"), "settings");
  assert.equal(parseDashboardSection("portfolio"), "dashboard");
  assert.equal(parseDashboardSection("committee"), "dashboard");
  assert.equal(parseDashboardSection("#settings"), "dashboard");
});

test("research stage parsing defaults to Overview and accepts only chain stages", () => {
  assert.equal(parseResearchStage(undefined), "overview");
  assert.equal(parseResearchStage("committee"), "committee");
  assert.equal(parseResearchStage("thesis"), "thesis");
  assert.equal(parseResearchStage("market"), "overview");
  assert.equal(parseResearchStage("settings"), "overview");
});

function facts(overrides: Partial<ResearchRunFacts> = {}): ResearchRunFacts {
  return {
    hasSecurity: true,
    hasEvidenceTrace: false,
    hasValuationContext: false,
    hasFinalizedRun: false,
    hasCommitteeReconciliation: false,
    hasReadiness: false,
    latestRunId: null,
    ...overrides,
  };
}

test("stages follow the chain order from overview to thesis", () => {
  assert.deepEqual(
    presentResearchStages(facts()).map((stage) => stage.id),
    ["overview", "evidence", "valuation", "opinions", "committee", "thesis"],
  );
});

test("every unavailable stage states why it is blocked and what comes next", () => {
  for (const stage of presentResearchStages(facts())) {
    if (stage.available) continue;
    assert.ok(
      stage.blockedReason && stage.blockedReason.length > 0,
      `${stage.id} must say why it is unavailable`,
    );
    assert.ok(
      stage.nextStep && stage.nextStep.length > 0,
      `${stage.id} must say what unblocks it`,
    );
  }
});

test("an available stage carries no blocked reason or next step", () => {
  const overview = presentResearchStages(facts())[0];
  assert.equal(overview.available, true);
  assert.equal(overview.blockedReason, null);
  assert.equal(overview.nextStep, null);
});

test("with no security selected every stage blocks on choosing one", () => {
  const stages = presentResearchStages(facts({ hasSecurity: false }));
  assert.ok(stages.every((stage) => !stage.available));
  assert.ok(
    stages.every((stage) => stage.blockedReason === "No security is selected."),
  );
});

test("stage artifacts unlock independently, without implying earlier stages", () => {
  const stages = presentResearchStages(
    facts({ hasEvidenceTrace: true, hasValuationContext: true }),
  );
  const byId = new Map(stages.map((stage) => [stage.id, stage]));
  assert.equal(byId.get("evidence")?.available, true);
  assert.equal(byId.get("valuation")?.available, true);
  assert.equal(byId.get("opinions")?.available, false);
  assert.equal(byId.get("thesis")?.available, false);
});

test("committee-owned stages link to the run that holds their artifact", () => {
  const stages = presentResearchStages(
    facts({
      hasFinalizedRun: true,
      hasCommitteeReconciliation: true,
      hasReadiness: true,
      latestRunId: "3f1b0c2e-9d4a-4c7f-b1e2-8a5d6c7f0912",
    }),
  );
  const byId = new Map(stages.map((stage) => [stage.id, stage]));
  assert.equal(
    byId.get("opinions")?.runHref,
    "/research-runs/3f1b0c2e-9d4a-4c7f-b1e2-8a5d6c7f0912",
  );
  assert.equal(
    byId.get("thesis")?.runHref,
    "/research-runs/3f1b0c2e-9d4a-4c7f-b1e2-8a5d6c7f0912",
  );
  assert.equal(byId.get("evidence")?.runHref, null, "evidence renders inline");
});

test("a blocked stage never links to a run, even when a run id exists", () => {
  const stages = presentResearchStages(
    facts({ latestRunId: "3f1b0c2e-9d4a-4c7f-b1e2-8a5d6c7f0912" }),
  );
  assert.ok(stages.every((stage) => stage.runHref === null));
});

test("the furthest stage reached is the deepest persisted artifact", () => {
  assert.equal(furthestAvailableStage(presentResearchStages(facts())), "overview");
  assert.equal(
    furthestAvailableStage(
      presentResearchStages(facts({ hasEvidenceTrace: true })),
    ),
    "evidence",
  );
  assert.equal(
    furthestAvailableStage(
      presentResearchStages(
        facts({
          hasEvidenceTrace: true,
          hasValuationContext: true,
          hasFinalizedRun: true,
          hasCommitteeReconciliation: true,
          hasReadiness: true,
        }),
      ),
    ),
    "thesis",
  );
});
