import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeEmailOtp,
  normalizeOperatorEmail,
  sendOperatorOtp,
  verifyOperatorOtp,
} from "./otp-auth.ts";

test("requests existing-operator email OTP without magic-link redirect", async () => {
  const requests: unknown[] = [];
  const auth = {
    async signInWithOtp(request: unknown) {
      requests.push(request);
      return { error: null };
    },
    async verifyOtp() {
      return { error: null };
    },
  };

  const email = normalizeOperatorEmail(" Operator@Example.com ");
  const result = await sendOperatorOtp(auth, email);

  assert.equal(email, "operator@example.com");
  assert.deepEqual(result, { error: null });
  assert.deepEqual(requests, [
    {
      email: "operator@example.com",
      options: { shouldCreateUser: false },
    },
  ]);
});

test("verifies exactly six numeric OTP digits against pending email", async () => {
  const requests: unknown[] = [];
  const auth = {
    async signInWithOtp() {
      return { error: null };
    },
    async verifyOtp(request: unknown) {
      requests.push(request);
      return { error: null };
    },
  };

  const token = normalizeEmailOtp(" 012345 ");
  const result = await verifyOperatorOtp(
    auth,
    "operator@example.com",
    token,
  );

  assert.equal(token, "012345");
  assert.deepEqual(result, { error: null });
  assert.deepEqual(requests, [
    {
      email: "operator@example.com",
      token: "012345",
      type: "email",
    },
  ]);
});

test("rejects malformed email and OTP before Supabase auth", () => {
  assert.throws(
    () => normalizeOperatorEmail("not-an-email"),
    /valid operator email/,
  );
  assert.throws(
    () => normalizeOperatorEmail(`${"a".repeat(245)}@example.com`),
    /valid operator email/,
  );
  for (const token of ["12345", "1234567", "12a456", ""]) {
    assert.throws(() => normalizeEmailOtp(token), /six-digit code/);
  }
});
