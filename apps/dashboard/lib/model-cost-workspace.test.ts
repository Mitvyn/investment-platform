import assert from "node:assert/strict";
import test from "node:test";

import { presentModelCostWorkspace } from "./model-cost-workspace.ts";

const owner = "11111111-1111-4111-8111-111111111111";
const run = "22222222-2222-4222-8222-222222222222";
const budgetId = "33333333-3333-4333-8333-333333333333";

const budget = {
  operator_id: owner,
  research_run_id: run,
  budget_id: budgetId,
  budget_policy_version: "research_budget.v1",
  currency: "USD",
  budget_state: "active",
  hard_cost_limit_usd: "1.000000",
  hard_token_limit: 100_000,
  current_reserved_cost_usd: "0.250000",
  current_reconciled_cost_usd: "0.000000",
  current_reserved_tokens: 25_000,
  current_reconciled_tokens: 0,
  remaining_cost_usd: "0.750000",
  remaining_tokens: 75_000,
  created_at: "2026-08-03T14:00:00Z",
};

const reserved = {
  operator_id: owner,
  research_run_id: run,
  execution_kind: "grader",
  execution_id: "44444444-4444-4444-8444-444444444444",
  attempt_number: 1,
  reservation_id: "55555555-5555-4555-8555-555555555555",
  budget_id: budgetId,
  budget_policy_version: "research_budget.v1",
  currency: "USD",
  price_card_version: "gpt_5_6_sol_usd.v1",
  reservation_state: "reserved",
  reserved_cost_usd: "0.250000",
  reconciled_cost_usd: null,
  reserved_tokens: 25_000,
  reconciled_tokens: null,
  reserved_at: "2026-08-03T14:01:00Z",
  reconciled_at: null,
};

const acceptedAttempt = {
  operator_id: owner,
  research_run_id: run,
  security_id: "66666666-6666-4666-8666-666666666666",
  execution_kind: "grader",
  execution_role: "moonshot",
  execution_id: reserved.execution_id,
  attempt_id: "77777777-7777-4777-8777-777777777777",
  attempt_number: 1,
  execution_state: "accepted",
  attempt_result: "accepted",
  provider: "openai",
  model: "gpt-5.6-sol",
  model_config_id: "gpt_5_6_sol.v1",
  prompt_version: "moonshot.v1",
  price_card_version: "gpt_5_6_sol_usd.v1",
  currency: "USD",
  price_card_state: "valid",
  validation_status: "passed",
  schema_valid: true,
  citations_valid: true,
  validation_error_count: 0,
  retry_recorded: false,
  input_tokens: 1_000,
  cached_input_tokens: 200,
  cache_write_tokens: 100,
  uncached_input_tokens: 700,
  output_tokens: 300,
  reasoning_tokens: 100,
  total_tokens: 1_300,
  tool_call_count: 0,
  usage_complete: true,
  reserved_cost_usd: "0.250000",
  reconciled_cost_usd: "0.012000",
  estimated_cost_usd: "0.012000",
  billed_cost_usd: "0.012000",
  reservation_state: "reconciled",
  budget_id: budgetId,
  budget_policy_version: "research_budget.v1",
  hard_cost_limit_usd: "1.000000",
  hard_token_limit: 100_000,
  current_reserved_cost_usd: "0.000000",
  current_reconciled_cost_usd: "0.024000",
  current_reserved_tokens: 0,
  current_reconciled_tokens: 2_600,
  remaining_cost_usd: "0.976000",
  remaining_tokens: 97_400,
  started_at: "2026-08-03T14:01:00Z",
  finished_at: "2026-08-03T14:01:02Z",
  duration_ms: 2_000,
};

test("presents empty accounting as unavailable rather than zero spend", () => {
  const presentation = presentModelCostWorkspace({
    budgets: [],
    reservations: [],
    attempts: [],
  });

  assert.deepEqual(presentation, {
    kind: "empty",
    status: {
      code: "empty",
      label: "No accounting records",
      variant: "attention",
    },
    description:
      "No persisted model budget, reservation, or attempt exists for this Research Run.",
    blockingReasons: ["No model accounting records are available"],
    summary: null,
    budgets: [],
    reservations: [],
    attempts: [],
  });
});

test("presents active reservation as partial accounting with remaining run budget", () => {
  const presentation = presentModelCostWorkspace({
    budgets: [budget],
    reservations: [reserved],
    attempts: [],
  });

  assert.equal(presentation.kind, "ready");
  assert.deepEqual(presentation.status, {
    code: "partial",
    label: "Accounting in progress",
    variant: "attention",
  });
  assert.equal(presentation.summary?.attemptCount, 0);
  assert.equal(presentation.summary?.reservationCount, 1);
  assert.equal(presentation.summary?.costs.reserved, "$0.250000");
  assert.equal(presentation.summary?.costs.reconciled, "Unavailable");
  assert.equal(presentation.summary?.costs.estimated, "Unavailable");
  assert.equal(presentation.budgets[0]?.remainingCost, "$0.750000");
  assert.equal(presentation.budgets[0]?.remainingTokens, "75,000");
  assert.equal(presentation.reservations[0]?.state, "reserved");
  assert.equal(presentation.reservations[0]?.executionId, reserved.execution_id);
  assert.equal(
    presentation.reservations[0]?.priceCard,
    "gpt_5_6_sol_usd.v1",
  );
});

test("keeps released reservations visible without inventing reconciled spend", () => {
  const presentation = presentModelCostWorkspace({
    budgets: [budget],
    reservations: [{ ...reserved, reservation_state: "released" }],
    attempts: [],
  });

  assert.equal(presentation.reservations[0]?.state, "released");
  assert.equal(presentation.reservations[0]?.reservedCost, "$0.250000");
  assert.equal(presentation.reservations[0]?.reconciledCost, "Unavailable");
  assert.equal(presentation.reservations[0]?.reconciledTokens, "Unavailable");
});

test("keeps missing usage and cost unknown and blocks complete accounting", () => {
  const incomplete = {
    ...acceptedAttempt,
    usage_complete: false,
    cached_input_tokens: null,
    estimated_cost_usd: null,
    reconciled_cost_usd: null,
    reservation_state: "released",
    finished_at: null,
    duration_ms: null,
  };
  const presentation = presentModelCostWorkspace({
    budgets: [budget],
    reservations: [],
    attempts: [incomplete],
  });

  assert.equal(presentation.status.code, "partial");
  assert.equal(presentation.attempts[0]?.tokens.cachedInput, "Unavailable");
  assert.equal(presentation.attempts[0]?.costs.estimated, "Unavailable");
  assert.equal(presentation.attempts[0]?.costs.reconciled, "Unavailable");
  assert.equal(presentation.summary?.tokens.cachedInput, "Unavailable");
  assert.equal(presentation.summary?.costs.estimated, "Unavailable");
  assert.ok(presentation.blockingReasons.includes("Usage is incomplete"));
  assert.ok(
    presentation.blockingReasons.includes("Reservation is not reconciled"),
  );
});

test("shows failed retry and incomplete accounting at same time", () => {
  const presentation = presentModelCostWorkspace({
    budgets: [budget],
    reservations: [],
    attempts: [{
      ...acceptedAttempt,
      attempt_result: "validation_error",
      validation_status: "failed",
      retry_recorded: true,
      usage_complete: false,
      input_tokens: null,
    }],
  });

  assert.equal(presentation.status.code, "failed_retried");
  assert.match(presentation.description, /accounting also remains incomplete/i);
  assert.ok(presentation.blockingReasons.includes("Usage is incomplete"));
});

test("active reservation blocks complete status beside a reconciled attempt", () => {
  const reconciledReservation = {
    ...reserved,
    reservation_state: "reconciled",
    reconciled_cost_usd: "0.012000",
    reconciled_tokens: 1_300,
    reconciled_at: "2026-08-03T14:01:02Z",
  };
  const activeReservation = {
    ...reserved,
    execution_kind: "synthesizer",
    execution_id: "99999999-9999-4999-8999-999999999999",
    reservation_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  };
  const presentation = presentModelCostWorkspace({
    budgets: [budget],
    reservations: [reconciledReservation, activeReservation],
    attempts: [acceptedAttempt],
  });

  assert.equal(presentation.status.code, "partial");
  assert.ok(
    presentation.blockingReasons.includes("Reservation remains active"),
  );
  assert.equal(presentation.summary?.costs.reconciled, "Partial · $0.012000 known");
});

test("rejects non-USD attempt and reservation rows before dollar formatting", () => {
  assert.throws(
    () => presentModelCostWorkspace({
      budgets: [budget],
      reservations: [{ ...reserved, currency: "EUR" }],
      attempts: [],
    }),
    /currency/,
  );
  assert.throws(
    () => presentModelCostWorkspace({
      budgets: [budget],
      reservations: [],
      attempts: [{ ...acceptedAttempt, currency: "EUR" }],
    }),
    /currency/,
  );
});

test("preserves failed validation and retry usage in accounting totals", () => {
  const failed = {
    ...acceptedAttempt,
    attempt_result: "validation_error",
    validation_status: "failed",
    schema_valid: false,
    citations_valid: false,
    validation_error_count: 2,
    retry_recorded: true,
  };
  const retry = {
    ...acceptedAttempt,
    attempt_id: "88888888-8888-4888-8888-888888888888",
    attempt_number: 2,
    retry_recorded: true,
  };
  const presentation = presentModelCostWorkspace({
    budgets: [{ ...budget, current_reserved_cost_usd: "0", current_reconciled_cost_usd: "0.024", current_reserved_tokens: 0, current_reconciled_tokens: 2_600, remaining_cost_usd: "0.976", remaining_tokens: 97_400 }],
    reservations: [],
    attempts: [failed, retry],
  });

  assert.deepEqual(presentation.status, {
    code: "failed_retried",
    label: "Failures or retries recorded",
    variant: "attention",
  });
  assert.equal(presentation.summary?.attemptCount, 2);
  assert.deepEqual(presentation.summary?.tokens, {
    input: "2,000",
    cachedInput: "400",
    cacheWrite: "200",
    uncachedInput: "1,400",
    output: "600",
    reasoning: "200",
    total: "2,600",
  });
  assert.deepEqual(presentation.summary?.validation, {
    passed: 1,
    failed: 1,
    notRun: 0,
    errorCount: 2,
    retryCount: 2,
  });
  assert.equal(presentation.summary?.costs.estimated, "$0.024000");
});

test("presents complete grader and Synthesizer accounting without hiding partial billed cost", () => {
  const synthesisAttempt = {
    ...acceptedAttempt,
    execution_kind: "synthesizer",
    execution_role: "synthesizer",
    execution_id: "99999999-9999-4999-8999-999999999999",
    attempt_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    prompt_version: "committee_synthesis.v1",
    schema_valid: null,
    citations_valid: null,
    billed_cost_usd: null,
  };
  const reconciledReservation = {
    ...reserved,
    reservation_state: "reconciled",
    reconciled_cost_usd: "0.012000",
    reconciled_tokens: 1_300,
    reconciled_at: "2026-08-03T14:01:02Z",
  };
  const presentation = presentModelCostWorkspace({
    budgets: [{
      ...budget,
      current_reserved_cost_usd: "0",
      current_reconciled_cost_usd: "0.024",
      current_reserved_tokens: 0,
      current_reconciled_tokens: 2_600,
      remaining_cost_usd: "0.976",
      remaining_tokens: 97_400,
    }],
    reservations: [
      reconciledReservation,
      {
        ...reconciledReservation,
        execution_kind: "synthesizer",
        execution_id: synthesisAttempt.execution_id,
        reservation_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      },
    ],
    attempts: [acceptedAttempt, synthesisAttempt],
  });

  assert.deepEqual(presentation.status, {
    code: "complete",
    label: "Accounting complete",
    variant: "verified",
  });
  assert.equal(presentation.summary?.roleCount, 2);
  assert.equal(presentation.summary?.costs.reconciled, "$0.024000");
  assert.equal(presentation.summary?.costs.billed, "Partial · $0.012000");
  assert.equal(presentation.attempts[1]?.kind, "synthesizer");
  assert.equal(presentation.attempts[1]?.validation.schema, "Not applicable");
});
