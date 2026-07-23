import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type {
  ReadinessGateResult,
  ThesisChain,
  ThesisCreationResult,
  ThesisVersion,
} from "../../../packages/types/readiness-thesis.ts";
import { presentReadinessThesisWorkspace } from "./readiness-thesis-workspace.ts";

const readiness = JSON.parse(readFileSync(
  new URL("../../../tests/fixtures/contracts/readiness_thesis/v1/decision-ready.json", import.meta.url),
  "utf8",
)) as ReadinessGateResult;
const thesis = JSON.parse(readFileSync(
  new URL("../../../tests/fixtures/contracts/readiness_thesis/v1/canonical-thesis.json", import.meta.url),
  "utf8",
)) as ThesisVersion;
const creation: ThesisCreationResult = {
  contract_version: "thesis_creation_result.v1",
  thesis_creation_result_id: "42000000-0000-4000-8000-000000000001",
  operator_id: readiness.operator_id,
  security_id: readiness.security_id,
  thesis_contract_id: readiness.thesis_contract_id,
  research_run_id: readiness.research_run_id,
  committee_result_id: readiness.committee_result_id,
  readiness_gate_result_id: readiness.readiness_gate_result_id,
  committee_status: readiness.committee_status,
  creation_outcome: "canonical_created",
  thesis_version_id: thesis.thesis_version_id,
  reason_code: "complete_committee_canonical_thesis",
  created_at: "2026-05-06T22:03:08Z",
};
const chain: ThesisChain = {
  contract_version: "thesis_chain.v1",
  operator_id: readiness.operator_id,
  security_id: readiness.security_id,
  thesis_contract_id: readiness.thesis_contract_id,
  active_canonical_thesis_version_id: thesis.thesis_version_id,
  canonical_versions: [thesis],
  provisional_branches: [],
  generated_at: "2026-05-06T22:03:09Z",
};

test("presents all eleven deterministic readiness checks and canonical thesis chain", () => {
  const presentation = presentReadinessThesisWorkspace({
    readiness,
    creation,
    thesis,
    chain,
  });

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  assert.equal(presentation.readiness.checks.length, 11);
  assert.equal(presentation.readiness.passedCount, 11);
  assert.equal(presentation.readiness.failedCount, 0);
  assert.equal(presentation.readiness.requestedDisposition, "Decision ready");
  assert.equal(presentation.readiness.finalDisposition, "Decision ready");
  assert.equal(presentation.thesis.outcome, "Canonical thesis created");
  assert.equal(presentation.thesis.version?.status, "Canonical");
  assert.equal(presentation.chain.canonicalVersions.length, 1);
  assert.equal(presentation.chain.provisionalBranches.length, 0);
  assert.equal(
    presentation.chain.activeCanonicalThesisVersionId,
    thesis.thesis_version_id,
  );
});

test("presents downgrade blockers and a non-superseding provisional branch", () => {
  const blocked = structuredClone(readiness);
  const failed = blocked.passed_checks.pop();
  assert.ok(failed);
  failed.reason_code = "missing_review_trigger";
  failed.explanation = "Required review trigger is absent.";
  blocked.failed_checks = [failed];
  blocked.blocking_reasons = [{
    reason_code: "missing_review_trigger",
    check_id: "thesis_required_contents_present",
    explanation: "A review trigger is required.",
  }];
  blocked.required_next_evidence = [{
    requirement_id: "review-trigger",
    description: "Add a source-backed review trigger.",
    affected_check_ids: ["thesis_required_contents_present"],
  }];
  blocked.committee_status = "complete_with_abstentions";
  blocked.readiness_status = "blocked";
  blocked.final_disposition = "deep_research";

  const provisional = structuredClone(thesis);
  provisional.thesis_version_id = "41000000-0000-4000-8000-000000000002";
  provisional.thesis_status = "provisional";
  provisional.previous_canonical_thesis_version_id = thesis.thesis_version_id;
  provisional.based_on_thesis_version_id = thesis.thesis_version_id;
  provisional.committee_status = "complete_with_abstentions";
  provisional.final_disposition = "deep_research";
  const provisionalCreation: ThesisCreationResult = {
    ...creation,
    thesis_creation_result_id: "42000000-0000-4000-8000-000000000002",
    committee_status: "complete_with_abstentions",
    creation_outcome: "provisional_created",
    thesis_version_id: provisional.thesis_version_id,
    reason_code: "abstention_committee_provisional_thesis",
  };
  const branchedChain: ThesisChain = {
    ...chain,
    canonical_versions: [thesis],
    provisional_branches: [provisional],
  };

  const presentation = presentReadinessThesisWorkspace({
    readiness: blocked,
    creation: provisionalCreation,
    thesis: provisional,
    chain: branchedChain,
  });

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  assert.equal(presentation.readiness.failedCount, 1);
  assert.equal(presentation.readiness.finalDisposition, "Deep research");
  assert.equal(presentation.readiness.blockingReasons[0]?.code, "missing_review_trigger");
  assert.equal(presentation.readiness.requiredNextEvidence[0]?.id, "review-trigger");
  assert.equal(presentation.thesis.outcome, "Provisional thesis created");
  assert.equal(
    presentation.chain.activeCanonicalThesisVersionId,
    thesis.thesis_version_id,
  );
  assert.equal(presentation.chain.provisionalBranches[0]?.basedOnThesisVersionId, thesis.thesis_version_id);
});

test("presents an explicit no-thesis result for incomplete committee status", () => {
  const incomplete = structuredClone(readiness);
  incomplete.committee_status = "incomplete_required_grader_failed";
  incomplete.requested_disposition = "deep_research";
  incomplete.final_disposition = "deep_research";
  incomplete.readiness_status = "not_requested";
  const noThesis: ThesisCreationResult = {
    ...creation,
    thesis_creation_result_id: "42000000-0000-4000-8000-000000000003",
    committee_status: "incomplete_required_grader_failed",
    creation_outcome: "no_thesis",
    thesis_version_id: null,
    reason_code: "incomplete_committee_no_thesis",
  };

  const presentation = presentReadinessThesisWorkspace({
    readiness: incomplete,
    creation: noThesis,
    thesis: null,
    chain,
  });

  assert.equal(presentation.kind, "ready");
  if (presentation.kind !== "ready") return;
  assert.equal(presentation.thesis.outcome, "No thesis created");
  assert.equal(presentation.thesis.version, null);
});
