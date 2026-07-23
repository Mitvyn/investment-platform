import assert from "node:assert/strict";
import test from "node:test";

import { createReadinessThesisLoader } from "./readiness-thesis-loader.ts";

const operatorId = "11111111-1111-4111-8111-111111111111";
const runId = "22222222-2222-4222-8222-222222222222";
const securityId = "33333333-3333-4333-8333-333333333333";
const committeeId = "44444444-4444-4444-8444-444444444444";
const memoId = "55555555-5555-4555-8555-555555555555";
const readinessId = "66666666-6666-4666-8666-666666666666";
const thesisId = "77777777-7777-4777-8777-777777777777";
const thesisContractId = "biotech_moonshot_catalyst_assessment";

const readiness = {
  operator_id: operatorId,
  research_run_id: runId,
  security_id: securityId,
  thesis_contract_id: thesisContractId,
  committee_result_id: committeeId,
  committee_memo_id: memoId,
  readiness_gate_result_id: readinessId,
};
const thesis = {
  operator_id: operatorId,
  research_run_id: runId,
  security_id: securityId,
  thesis_contract_id: thesisContractId,
  readiness_gate_result_id: readinessId,
  thesis_version_id: thesisId,
};
const creation = {
  operator_id: operatorId,
  research_run_id: runId,
  security_id: securityId,
  thesis_contract_id: thesisContractId,
  readiness_gate_result_id: readinessId,
  committee_result_id: committeeId,
  creation_outcome: "canonical_created" as const,
  thesis_version_id: thesisId,
};
const chain = {
  operator_id: operatorId,
  security_id: securityId,
  thesis_contract_id: thesisContractId,
  active_canonical_thesis_version_id: thesisId,
  canonical_versions: [thesis],
  provisional_branches: [],
};

test("authenticated operator loads one exact readiness, thesis result, and ownership chain", async () => {
  const requests: Array<{ source: string; values: string[] }> = [];
  const load = createReadinessThesisLoader(
    async (...values) => {
      requests.push({ source: "readiness", values });
      return [{
        operator_id: operatorId,
        research_run_id: runId,
        committee_result_id: committeeId,
        committee_memo_id: memoId,
        canonical_readiness: readiness,
      }];
    },
    async (...values) => {
      requests.push({ source: "thesis", values });
      return [{
        operator_id: operatorId,
        research_run_id: runId,
        readiness_gate_result_id: readinessId,
        creation_outcome: "canonical_created",
        canonical_creation_result: creation,
        canonical_thesis: thesis,
      }];
    },
    async (...values) => {
      requests.push({ source: "chain", values });
      return [{
        operator_id: operatorId,
        security_id: securityId,
        thesis_contract_id: thesisContractId,
        canonical_chain: chain,
      }];
    },
    (value) => value as typeof readiness,
    (value) => value as typeof creation,
    (value) => value as typeof thesis,
    (value) => value as typeof chain,
  );

  assert.deepEqual(await load(operatorId, runId, securityId, thesisContractId), {
    readiness,
    creation,
    thesis,
    chain,
  });
  assert.deepEqual(requests, [
    { source: "readiness", values: [operatorId, runId] },
    { source: "thesis", values: [operatorId, runId] },
    { source: "chain", values: [operatorId, securityId, thesisContractId] },
  ]);
});

test("created thesis must resolve exactly once in the owner chain", async () => {
  const load = createReadinessThesisLoader(
    async () => [{
      operator_id: operatorId,
      research_run_id: runId,
      committee_result_id: committeeId,
      committee_memo_id: memoId,
      canonical_readiness: readiness,
    }],
    async () => [{
      operator_id: operatorId,
      research_run_id: runId,
      readiness_gate_result_id: readinessId,
      creation_outcome: "canonical_created",
      canonical_creation_result: creation,
      canonical_thesis: thesis,
    }],
    async () => [{
      operator_id: operatorId,
      security_id: securityId,
      thesis_contract_id: thesisContractId,
      canonical_chain: {
        ...chain,
        active_canonical_thesis_version_id: null,
        canonical_versions: [],
      },
    }],
    (value) => value as typeof readiness,
    (value) => value as typeof creation,
    (value) => value as typeof thesis,
    (value) => value as typeof chain,
  );

  await assert.rejects(
    load(operatorId, runId, securityId, thesisContractId),
    /created thesis does not resolve exactly once in ownership chain/,
  );
});

test("loader rejects duplicate canonical rows from every owner-scoped view", async () => {
  const readinessRow = {
    operator_id: operatorId,
    research_run_id: runId,
    committee_result_id: committeeId,
    committee_memo_id: memoId,
    canonical_readiness: readiness,
  };
  const thesisRow = {
    operator_id: operatorId,
    research_run_id: runId,
    readiness_gate_result_id: readinessId,
    creation_outcome: "canonical_created" as const,
    canonical_creation_result: creation,
    canonical_thesis: thesis,
  };
  const chainRow = {
    operator_id: operatorId,
    security_id: securityId,
    thesis_contract_id: thesisContractId,
    canonical_chain: chain,
  };

  for (const duplicate of ["readiness", "thesis", "chain"] as const) {
    const load = createReadinessThesisLoader(
      async () => duplicate === "readiness" ? [readinessRow, readinessRow] : [readinessRow],
      async () => duplicate === "thesis" ? [thesisRow, thesisRow] : [thesisRow],
      async () => duplicate === "chain" ? [chainRow, chainRow] : [chainRow],
      (value) => value as typeof readiness,
      (value) => value as typeof creation,
      (value) => value as typeof thesis,
      (value) => value as typeof chain,
    );
    await assert.rejects(
      load(operatorId, runId, securityId, thesisContractId),
      /at most one/,
    );
  }
});

test("loader rejects owner, run, readiness, and outcome mismatches", async () => {
  const load = createReadinessThesisLoader(
    async () => [{
      operator_id: operatorId,
      research_run_id: runId,
      committee_result_id: committeeId,
      committee_memo_id: memoId,
      canonical_readiness: readiness,
    }],
    async () => [{
      operator_id: operatorId,
      research_run_id: runId,
      readiness_gate_result_id: readinessId,
      creation_outcome: "no_thesis" as const,
      canonical_creation_result: { ...creation, creation_outcome: "no_thesis" as const },
      canonical_thesis: thesis,
    }],
    async () => [{
      operator_id: operatorId,
      security_id: securityId,
      thesis_contract_id: thesisContractId,
      canonical_chain: chain,
    }],
    (value) => value as typeof readiness,
    (value) => value as typeof creation,
    (value) => value as typeof thesis,
    (value) => value as typeof chain,
  );

  await assert.rejects(
    load(operatorId, runId, securityId, thesisContractId),
    /outside requested owner, run, readiness, or creation scope/,
  );
});

test("missing current readiness returns existing ownership history without inventing a thesis", async () => {
  const load = createReadinessThesisLoader(
    async () => [],
    async () => [],
    async () => [{
      operator_id: operatorId,
      security_id: securityId,
      thesis_contract_id: thesisContractId,
      canonical_chain: chain,
    }],
    (value) => value as typeof readiness,
    (value) => value as typeof creation,
    (value) => value as typeof thesis,
    (value) => value as typeof chain,
  );

  assert.deepEqual(
    await load(operatorId, runId, securityId, thesisContractId),
    { readiness: null, creation: null, thesis: null, chain },
  );
});
