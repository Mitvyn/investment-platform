import assert from "node:assert/strict";
import test from "node:test";

import { createExistingThesisChainLoader } from "./existing-thesis-chain-loader.ts";

const operatorId = "11111111-1111-4111-8111-111111111111";
const securityId = "33333333-3333-4333-8333-333333333333";
const thesisContractId = "biotech_moonshot_catalyst_assessment";
const chain = {
  operator_id: operatorId,
  security_id: securityId,
  thesis_contract_id: thesisContractId,
};

test("missing current memo can still load the existing owner-scoped thesis chain", async () => {
  const load = createExistingThesisChainLoader(
    async () => [{
      operator_id: operatorId,
      security_id: securityId,
      thesis_contract_id: thesisContractId,
      canonical_chain: chain,
    }],
    (value) => value as typeof chain,
  );

  assert.deepEqual(
    await load(operatorId, securityId, thesisContractId),
    chain,
  );
});

test("existing thesis-chain fallback rejects duplicate or foreign rows", async () => {
  const row = {
    operator_id: operatorId,
    security_id: securityId,
    thesis_contract_id: thesisContractId,
    canonical_chain: chain,
  };
  const duplicate = createExistingThesisChainLoader(
    async () => [row, row],
    (value) => value as typeof chain,
  );
  const foreign = createExistingThesisChainLoader(
    async () => [{ ...row, operator_id: "99999999-9999-4999-8999-999999999999" }],
    (value) => value as typeof chain,
  );

  await assert.rejects(
    duplicate(operatorId, securityId, thesisContractId),
    /at most one thesis chain/,
  );
  await assert.rejects(
    foreign(operatorId, securityId, thesisContractId),
    /outside requested ownership scope/,
  );
});
