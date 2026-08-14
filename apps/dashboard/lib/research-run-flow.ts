import { loadEvidenceBundle } from "./evidence-bundles.ts";
import { loadExistingThesisChain } from "./existing-thesis-chains.ts";
import { loadCommitteeMemo } from "./committee-memos.ts";
import { loadGraderCommittee } from "./grader-committees.ts";
import { loadGraderExecutions } from "./grader-executions.ts";
import { loadOperatorDecisions } from "./operator-decisions.ts";
import { projectResearchRunAuditWorkspace } from "./research-run-audit-projection.ts";
import { loadResearchRun } from "./research-runs.ts";
import { loadReadinessThesis } from "./readiness-theses.ts";
import { loadValuationSnapshot } from "./valuation-snapshots.ts";

/**
 * Loads one owner-scoped Research Run and its immutable downstream artifacts.
 *
 * Both the dedicated audit route and the single-page Research flow use this
 * loader. Keeping one composition boundary prevents those surfaces from
 * drifting on ownership, evidence, or provenance checks.
 */
export async function loadResearchRunFlow(
  operatorId: string,
  runId: string,
) {
  const run = await loadResearchRun(operatorId, runId);
  if (run === null) return null;

  const bundle = await loadEvidenceBundle(operatorId, run.id);
  const valuationSnapshot = await loadValuationSnapshot(operatorId, run.id);
  const graderExecutions =
    bundle === null
      ? []
      : await loadGraderExecutions(operatorId, run.id, {
          evidenceBundleId: bundle.id,
          evidenceBundleHash: bundle.bundle_hash,
          evidenceIds: bundle.manifest.map((item) => item.item_id),
          calculationIds: valuationSnapshot?.calculation_ids ?? [],
        });
  const graderCommittee =
    bundle === null
      ? null
      : await loadGraderCommittee(operatorId, run.id, {
          evidenceBundleId: bundle.id,
          evidenceBundleHash: bundle.bundle_hash,
          evidenceIds: bundle.manifest.map((item) => item.item_id),
          calculationIds: valuationSnapshot?.calculation_ids ?? [],
        });
  const committeeMemo =
    bundle === null || graderCommittee === null
      ? null
      : await loadCommitteeMemo(operatorId, run.id, graderCommittee, {
          evidenceIds: bundle.manifest.map((item) => item.item_id),
          calculationIds: valuationSnapshot?.calculation_ids ?? [],
        });
  const readinessThesis =
    bundle === null || graderCommittee === null || committeeMemo === null
      ? {
          readiness: null,
          creation: null,
          thesis: null,
          chain: await loadExistingThesisChain(
            operatorId,
            run.security_id,
            run.thesis_contract_id,
          ),
        }
      : await loadReadinessThesis(operatorId, {
          run,
          bundle,
          committee: graderCommittee,
          memo: committeeMemo,
          allowedReferenceIds: [
            ...bundle.manifest.map((item) => item.item_id),
            ...(valuationSnapshot?.calculation_ids ?? []),
            ...committeeMemo.statements.map((statement) => statement.statement_id),
            ...committeeMemo.disagreement_records.map(
              (disagreement) => disagreement.disagreement_id,
            ),
          ],
        });
  const operatorDecisions = await loadOperatorDecisions(
    operatorId,
    run.security_id,
    run.thesis_contract_id,
  );

  return projectResearchRunAuditWorkspace(operatorId, {
    run,
    bundle,
    valuationSnapshot,
    graderExecutions,
    committee: graderCommittee,
    memo: committeeMemo,
    readinessThesis,
    operatorDecisions,
  });
}
