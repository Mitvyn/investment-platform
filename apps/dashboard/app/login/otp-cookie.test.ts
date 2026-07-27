import assert from "node:assert/strict";
import test from "node:test";

import { pendingOtpCookieOptions } from "./otp-cookie.ts";

test("desktop OTP cookie remains usable on loopback HTTP", () => {
  assert.deepEqual(
    pendingOtpCookieOptions({
      IROS_DESKTOP: "1",
      NODE_ENV: "production",
    }),
    {
      httpOnly: true,
      maxAge: 10 * 60,
      path: "/login",
      sameSite: "lax",
      secure: false,
    },
  );
});

test("hosted production OTP cookie remains secure", () => {
  assert.equal(
    pendingOtpCookieOptions({
      NODE_ENV: "production",
    }).secure,
    true,
  );
});
