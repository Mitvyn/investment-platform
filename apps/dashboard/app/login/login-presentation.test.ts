import assert from "node:assert/strict";
import test from "node:test";

import { presentLoginFeedback } from "./login-presentation.ts";

test("login feedback announces successful and failed sign-in requests", () => {
  assert.deepEqual(
    presentLoginFeedback({
      error: "Operator account is not provisioned",
      sent: "1",
    }),
    [
      {
        message: "Code sent. Enter the six-digit code from your email.",
        role: "status",
        tone: "verified",
      },
      {
        message: "Operator account is not provisioned",
        role: "alert",
        tone: "destructive",
      },
    ],
  );
});
