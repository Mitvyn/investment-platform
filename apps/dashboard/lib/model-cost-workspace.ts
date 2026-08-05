import type { ModelCostData } from "./model-cost-loader.ts";

type StatusVariant = "verified" | "attention" | "destructive";

export type ModelCostPresentation = {
  kind: "empty" | "ready";
  status: {
    code: "empty" | "partial" | "failed_retried" | "complete";
    label: string;
    variant: StatusVariant;
  };
  description: string;
  blockingReasons: string[];
  summary: ModelCostSummary | null;
  budgets: ModelCostBudgetPresentation[];
  reservations: ModelCostReservationPresentation[];
  attempts: ModelCostAttemptPresentation[];
};

type TokenSummary = {
  input: string;
  cachedInput: string;
  cacheWrite: string;
  uncachedInput: string;
  output: string;
  reasoning: string;
  total: string;
};

type ModelCostSummary = {
  attemptCount: number;
  reservationCount: number;
  roleCount: number;
  tokens: TokenSummary;
  costs: {
    reserved: string;
    reconciled: string;
    estimated: string;
    billed: string;
  };
  validation: {
    passed: number;
    failed: number;
    notRun: number;
    errorCount: number;
    retryCount: number;
  };
};

type ModelCostBudgetPresentation = {
  id: string;
  policy: string;
  state: string;
  hardLimit: string;
  reconciledCost: string;
  reservedCost: string;
  remainingCost: string;
  hardTokens: string;
  reconciledTokens: string;
  reservedTokens: string;
  remainingTokens: string;
};

type ModelCostReservationPresentation = {
  id: string;
  executionId: string;
  kind: string;
  attemptNumber: number;
  state: string;
  budgetPolicy: string;
  priceCard: string;
  reservedCost: string;
  reconciledCost: string;
  reservedTokens: string;
  reconciledTokens: string;
  reservedAt: string;
  reconciledAt: string;
};

type ModelCostAttemptPresentation = {
  id: string;
  role: string;
  kind: string;
  number: number;
  result: string;
  status: { label: string; variant: StatusVariant };
  provider: string;
  model: string;
  modelConfig: string;
  prompt: string;
  priceCard: string;
  priceCardState: string;
  validation: {
    status: string;
    errorCount: number;
    schema: string;
    citations: string;
  };
  retryRecorded: boolean;
  usageComplete: boolean;
  tokens: TokenSummary;
  costs: {
    reserved: string;
    reconciled: string;
    estimated: string;
    billed: string;
  };
  started: string;
  finished: string;
  duration: string;
};

function numberValue(value: unknown, label: string): number {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new TypeError(`invalid model accounting ${label}`);
  }
  return parsed;
}

function optionalNumber(value: unknown, label: string): number | null {
  return value === null || value === undefined ? null : numberValue(value, label);
}

function textValue(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`invalid model accounting ${label}`);
  }
  return value;
}

function formatUsd(value: number) {
  return `$${value.toFixed(6)}`;
}

function formatTokens(value: number) {
  return value.toLocaleString("en-US");
}

function formatDateTime(value: unknown, label: string) {
  const checked = textValue(value, label);
  const timestamp = new Date(checked);
  if (Number.isNaN(timestamp.getTime())) {
    throw new TypeError(`invalid model accounting ${label}`);
  }
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(timestamp);
}

const unknownTokens: TokenSummary = {
  input: "Unavailable",
  cachedInput: "Unavailable",
  cacheWrite: "Unavailable",
  uncachedInput: "Unavailable",
  output: "Unavailable",
  reasoning: "Unavailable",
  total: "Unavailable",
};

function formatOptionalUsd(value: unknown, label: string) {
  const checked = optionalNumber(value, label);
  return checked === null ? "Unavailable" : formatUsd(checked);
}

function summarizeNumbers(
  values: Array<number | null>,
  formatter: (value: number) => string,
) {
  const known = values.filter((value): value is number => value !== null);
  if (known.length === 0) return "Unavailable";
  const formatted = formatter(known.reduce((total, value) => total + value, 0));
  return known.length === values.length ? formatted : `Partial · ${formatted} known`;
}

function presentBudgets(data: ModelCostData): ModelCostBudgetPresentation[] {
  return data.budgets.map((budget) => {
    if (budget.currency !== "USD") {
      throw new TypeError("invalid model accounting currency");
    }
    return {
      id: textValue(budget.budget_id, "budget ID"),
      policy: textValue(budget.budget_policy_version, "budget policy"),
      state: textValue(budget.budget_state, "budget state"),
      hardLimit: formatUsd(numberValue(budget.hard_cost_limit_usd, "hard cost")),
      reconciledCost: formatUsd(
        numberValue(budget.current_reconciled_cost_usd, "reconciled cost"),
      ),
      reservedCost: formatUsd(
        numberValue(budget.current_reserved_cost_usd, "reserved cost"),
      ),
      remainingCost: formatUsd(
        numberValue(budget.remaining_cost_usd, "remaining cost"),
      ),
      hardTokens: formatTokens(
        numberValue(budget.hard_token_limit, "hard tokens"),
      ),
      reconciledTokens: formatTokens(
        numberValue(budget.current_reconciled_tokens, "reconciled tokens"),
      ),
      reservedTokens: formatTokens(
        numberValue(budget.current_reserved_tokens, "reserved tokens"),
      ),
      remainingTokens: formatTokens(
        numberValue(budget.remaining_tokens, "remaining tokens"),
      ),
    };
  });
}

function presentReservations(
  data: ModelCostData,
): ModelCostReservationPresentation[] {
  return data.reservations.map((reservation) => {
    if (reservation.currency !== "USD") {
      throw new TypeError("invalid model accounting currency");
    }
    const reconciledCost = optionalNumber(
      reservation.reconciled_cost_usd,
      "reservation reconciled cost",
    );
    const reconciledTokens = optionalNumber(
      reservation.reconciled_tokens,
      "reservation reconciled tokens",
    );
    return {
      id: textValue(reservation.reservation_id, "reservation ID"),
      executionId: textValue(reservation.execution_id, "reservation execution ID"),
      kind: textValue(reservation.execution_kind, "reservation execution kind"),
      attemptNumber: numberValue(
        reservation.attempt_number,
        "reservation attempt number",
      ),
      state: textValue(reservation.reservation_state, "reservation state"),
      budgetPolicy: textValue(
        reservation.budget_policy_version,
        "reservation budget policy",
      ),
      priceCard: textValue(
        reservation.price_card_version,
        "reservation price card",
      ),
      reservedCost: formatUsd(
        numberValue(reservation.reserved_cost_usd, "reservation reserved cost"),
      ),
      reconciledCost:
        reconciledCost === null ? "Unavailable" : formatUsd(reconciledCost),
      reservedTokens: formatTokens(
        numberValue(reservation.reserved_tokens, "reservation reserved tokens"),
      ),
      reconciledTokens:
        reconciledTokens === null
          ? "Unavailable"
          : formatTokens(reconciledTokens),
      reservedAt: formatDateTime(reservation.reserved_at, "reservation start"),
      reconciledAt:
        reservation.reconciled_at === null
          ? "Not reconciled"
          : formatDateTime(reservation.reconciled_at, "reservation reconciliation"),
    };
  });
}

function attemptTokens(
  attempt: ModelCostData["attempts"][number],
): {
  values: Record<keyof TokenSummary, number>;
  known: Record<keyof TokenSummary, boolean>;
  presentation: TokenSummary;
} {
  const raw = {
    input: optionalNumber(attempt.input_tokens, "input tokens"),
    cachedInput: optionalNumber(attempt.cached_input_tokens, "cached input tokens"),
    cacheWrite: optionalNumber(attempt.cache_write_tokens, "cache-write tokens"),
    uncachedInput: optionalNumber(attempt.uncached_input_tokens, "uncached input tokens"),
    output: optionalNumber(attempt.output_tokens, "output tokens"),
    reasoning: optionalNumber(attempt.reasoning_tokens, "reasoning tokens"),
    total: optionalNumber(attempt.total_tokens, "total tokens"),
  };
  const complete = attempt.usage_complete === true;
  if (complete && Object.values(raw).some((value) => value === null)) {
    throw new TypeError("complete model usage has missing token categories");
  }
  const values = Object.fromEntries(
    Object.entries(raw).map(([key, value]) => [key, value ?? 0]),
  ) as Record<keyof TokenSummary, number>;
  const known = Object.fromEntries(
    Object.entries(raw).map(([key, value]) => [key, value !== null]),
  ) as Record<keyof TokenSummary, boolean>;
  if (
    complete &&
    (values.input !==
      values.cachedInput + values.cacheWrite + values.uncachedInput ||
      values.total !== values.input + values.output ||
      values.reasoning > values.output)
  ) {
    throw new TypeError("model token categories do not reconcile");
  }
  return {
    values,
    known,
    presentation: Object.fromEntries(
      Object.entries(raw).map(([key, value]) => [
        key,
        value === null ? "Unavailable" : formatTokens(value),
      ]),
    ) as TokenSummary,
  };
}

function presentAttempts(data: ModelCostData): {
  attempts: ModelCostAttemptPresentation[];
  totals: Record<keyof TokenSummary, number>;
  knownCounts: Record<keyof TokenSummary, number>;
} {
  const totals: Record<keyof TokenSummary, number> = {
    input: 0,
    cachedInput: 0,
    cacheWrite: 0,
    uncachedInput: 0,
    output: 0,
    reasoning: 0,
    total: 0,
  };
  const knownCounts: Record<keyof TokenSummary, number> = {
    input: 0,
    cachedInput: 0,
    cacheWrite: 0,
    uncachedInput: 0,
    output: 0,
    reasoning: 0,
    total: 0,
  };
  const attempts = data.attempts.map((attempt) => {
    if (attempt.currency !== "USD") {
      throw new TypeError("invalid model accounting currency");
    }
    const tokenResult = attemptTokens(attempt);
    for (const key of Object.keys(totals) as Array<keyof TokenSummary>) {
      totals[key] += tokenResult.values[key];
      if (tokenResult.known[key]) knownCounts[key] += 1;
    }
    const validationStatus = textValue(
      attempt.validation_status,
      "validation status",
    );
    const attemptResult = textValue(attempt.attempt_result, "attempt result");
    const status =
      validationStatus === "failed" ||
      attemptResult === "transport_error" ||
      attemptResult === "validation_error"
        ? { label: "Failed", variant: "destructive" as const }
        : validationStatus === "passed"
          ? { label: "Validated", variant: "verified" as const }
          : { label: "Incomplete", variant: "attention" as const };
    const finished = attempt.finished_at;
    const duration = optionalNumber(attempt.duration_ms, "duration");
    return {
      id: textValue(attempt.attempt_id, "attempt ID"),
      role: textValue(attempt.execution_role, "execution role").replaceAll("_", " "),
      kind: textValue(attempt.execution_kind, "execution kind"),
      number: numberValue(attempt.attempt_number, "attempt number"),
      result: attemptResult.replaceAll("_", " "),
      status,
      provider: textValue(attempt.provider, "provider"),
      model: textValue(attempt.model, "model"),
      modelConfig: textValue(attempt.model_config_id, "model config"),
      prompt: textValue(attempt.prompt_version, "prompt version"),
      priceCard: textValue(attempt.price_card_version, "price card"),
      priceCardState: textValue(attempt.price_card_state, "price-card state"),
      validation: {
        status: validationStatus,
        errorCount: numberValue(
          attempt.validation_error_count,
          "validation error count",
        ),
        schema:
          attempt.schema_valid === null
            ? "Not applicable"
            : attempt.schema_valid === true
              ? "Pass"
              : "Fail",
        citations:
          attempt.citations_valid === null
            ? "Not applicable"
            : attempt.citations_valid === true
              ? "Pass"
              : "Fail",
      },
      retryRecorded: attempt.retry_recorded === true,
      usageComplete: attempt.usage_complete === true,
      tokens: tokenResult.presentation,
      costs: {
        reserved: formatOptionalUsd(attempt.reserved_cost_usd, "reserved cost"),
        reconciled: formatOptionalUsd(
          attempt.reconciled_cost_usd,
          "reconciled cost",
        ),
        estimated: formatOptionalUsd(attempt.estimated_cost_usd, "estimated cost"),
        billed: formatOptionalUsd(attempt.billed_cost_usd, "billed cost"),
      },
      started: formatDateTime(attempt.started_at, "attempt start"),
      finished:
        finished === null ? "Not finished" : formatDateTime(finished, "attempt finish"),
      duration: duration === null ? "Unavailable" : `${duration.toLocaleString("en-US")} ms`,
    };
  });
  return { attempts, totals, knownCounts };
}

export function presentModelCostWorkspace(
  data: ModelCostData,
): ModelCostPresentation {
  if (
    data.budgets.length === 0 &&
    data.reservations.length === 0 &&
    data.attempts.length === 0
  ) {
    return {
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
    };
  }

  if (data.attempts.length === 0) {
    const reservedCost = data.reservations.reduce(
      (total, reservation) =>
        total + numberValue(reservation.reserved_cost_usd, "reserved cost"),
      0,
    );
    return {
      kind: "ready",
      status: {
        code: "partial",
        label: "Accounting in progress",
        variant: "attention",
      },
      description:
        "Budget or reservation state exists, but no terminal model attempt is available yet.",
      blockingReasons: ["No terminal model attempts are available"],
      summary: {
        attemptCount: 0,
        reservationCount: data.reservations.length,
        roleCount: 0,
        tokens: unknownTokens,
        costs: {
          reserved: formatUsd(reservedCost),
          reconciled: summarizeNumbers(
            data.reservations.map((reservation) =>
              optionalNumber(
                reservation.reconciled_cost_usd,
                "reservation reconciled cost",
              ),
            ),
            formatUsd,
          ),
          estimated: "Unavailable",
          billed: "Unavailable",
        },
        validation: {
          passed: 0,
          failed: 0,
          notRun: 0,
          errorCount: 0,
          retryCount: 0,
        },
      },
      budgets: presentBudgets(data),
      reservations: presentReservations(data),
      attempts: [],
    };
  }

  const presented = presentAttempts(data);
  const failedOrRetried = data.attempts.some(
    (attempt) =>
      attempt.retry_recorded === true ||
      attempt.validation_status === "failed" ||
      attempt.attempt_result === "transport_error" ||
      attempt.attempt_result === "validation_error",
  );
  const blockingReasons = new Set<string>();
  if (data.budgets.length === 0) blockingReasons.add("Run budget is unavailable");
  if (data.reservations.length === 0) {
    blockingReasons.add("Reservation ledger is unavailable");
  }
  for (const reservation of data.reservations) {
    if (reservation.reservation_state === "reserved") {
      blockingReasons.add("Reservation remains active");
    } else if (
      !["reconciled", "released"].includes(String(reservation.reservation_state))
    ) {
      blockingReasons.add("Reservation state is invalid");
    }
    if (
      optionalNumber(
        reservation.reconciled_cost_usd,
        "reservation reconciled cost",
      ) === null ||
      optionalNumber(
        reservation.reconciled_tokens,
        "reservation reconciled tokens",
      ) === null ||
      reservation.reconciled_at === null ||
      reservation.reconciled_at === undefined
    ) {
      blockingReasons.add("Reservation settlement is incomplete");
    }
  }
  for (const attempt of data.attempts) {
    if (attempt.usage_complete !== true) blockingReasons.add("Usage is incomplete");
    if (attempt.validation_status !== "passed") {
      blockingReasons.add("Validation has not passed");
    }
    if (attempt.price_card_state !== "valid") {
      blockingReasons.add("Price card is not valid");
    }
    if (attempt.reservation_state !== "reconciled") {
      blockingReasons.add("Reservation is not reconciled");
    }
    if (optionalNumber(attempt.reconciled_cost_usd, "reconciled cost") === null) {
      blockingReasons.add("Reconciled cost is unavailable");
    }
    if (
      attempt.finished_at === null ||
      attempt.finished_at === undefined ||
      optionalNumber(attempt.duration_ms, "duration") === null
    ) {
      blockingReasons.add("Terminal timing is incomplete");
    }
  }
  const partial = blockingReasons.size > 0;
  const status = failedOrRetried
    ? {
        code: "failed_retried" as const,
        label: "Failures or retries recorded",
        variant: "attention" as const,
      }
    : partial
      ? {
          code: "partial" as const,
          label: "Accounting incomplete",
          variant: "attention" as const,
        }
      : {
          code: "complete" as const,
          label: "Accounting complete",
          variant: "verified" as const,
        };
  const estimatedValues = data.attempts.map((attempt) =>
    optionalNumber(attempt.estimated_cost_usd, "estimated cost"),
  );
  const billedValues = data.attempts.map((attempt) =>
    optionalNumber(attempt.billed_cost_usd, "billed cost"),
  );
  const reservationSource =
    data.reservations.length === 0 ? data.attempts : data.reservations;
  const reservedValues = reservationSource.map((row) =>
    optionalNumber(row.reserved_cost_usd, "reserved cost"),
  );
  const reconciledValues = reservationSource.map((row) =>
    optionalNumber(row.reconciled_cost_usd, "reconciled cost"),
  );
  const validation = {
    passed: data.attempts.filter(
      (attempt) => attempt.validation_status === "passed",
    ).length,
    failed: data.attempts.filter(
      (attempt) => attempt.validation_status === "failed",
    ).length,
    notRun: data.attempts.filter(
      (attempt) => attempt.validation_status === "not_run",
    ).length,
    errorCount: data.attempts.reduce(
      (total, attempt) =>
        total + numberValue(attempt.validation_error_count, "validation errors"),
      0,
    ),
    retryCount: data.attempts.filter(
      (attempt) => attempt.retry_recorded === true,
    ).length,
  };
  return {
    kind: "ready",
    status,
    description:
      status.code === "complete"
        ? "All persisted attempts have complete usage, valid pricing, and terminal accounting."
        : status.code === "failed_retried"
          ? partial
            ? "Failed or retried attempts remain included; accounting also remains incomplete."
            : "Failed or retried attempts remain included in token and cost totals."
          : "Some persisted usage, validation, pricing, or reservation state is incomplete.",
    blockingReasons: [...blockingReasons],
    summary: {
      attemptCount: data.attempts.length,
      reservationCount: data.reservations.length,
      roleCount: new Set(
        data.attempts.map(
          (attempt) => `${String(attempt.execution_kind)}:${String(attempt.execution_role)}`,
        ),
      ).size,
      tokens: Object.fromEntries(
        (Object.keys(presented.totals) as Array<keyof TokenSummary>).map((key) => [
          key,
          presented.knownCounts[key] === 0
            ? "Unavailable"
            : presented.knownCounts[key] === data.attempts.length
              ? formatTokens(presented.totals[key])
              : `Partial · ${formatTokens(presented.totals[key])} known`,
        ]),
      ) as TokenSummary,
      costs: {
        reserved: summarizeNumbers(reservedValues, formatUsd),
        reconciled: summarizeNumbers(reconciledValues, formatUsd),
        estimated: summarizeNumbers(estimatedValues, formatUsd),
        billed: billedValues.every((value) => value === null)
          ? "Unavailable"
          : `${billedValues.some((value) => value === null) ? "Partial · " : ""}${formatUsd(
              billedValues.reduce<number>(
                (total, value) => total + (value ?? 0),
                0,
              ),
            )}`,
      },
      validation,
    },
    budgets: presentBudgets(data),
    reservations: presentReservations(data),
    attempts: presented.attempts,
  };
}
