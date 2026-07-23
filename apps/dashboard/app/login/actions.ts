"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { createClient } from "../../lib/supabase/server";
import {
  normalizeEmailOtp,
  normalizeOperatorEmail,
  sendOperatorOtp,
  verifyOperatorOtp,
} from "./otp-auth";

const PENDING_EMAIL_COOKIE = "iros_pending_otp_email";
const PENDING_EMAIL_MAX_AGE_SECONDS = 10 * 60;
const COOKIE_PATH = "/login";

function loginError(message: string, sent = false): never {
  const state = sent ? "sent=1&" : "";
  redirect(`/login?${state}error=${encodeURIComponent(message)}`);
}

async function pendingEmail(): Promise<string | null> {
  const cookieStore = await cookies();
  return cookieStore.get(PENDING_EMAIL_COOKIE)?.value ?? null;
}

async function rememberPendingEmail(email: string): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.set(PENDING_EMAIL_COOKIE, email, {
    httpOnly: true,
    maxAge: PENDING_EMAIL_MAX_AGE_SECONDS,
    path: COOKIE_PATH,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
  });
}

async function clearPendingEmail(): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.set(PENDING_EMAIL_COOKIE, "", {
    httpOnly: true,
    maxAge: 0,
    path: COOKIE_PATH,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
  });
}

export async function requestEmailOtp(formData: FormData) {
  let email: string;
  try {
    email = normalizeOperatorEmail(String(formData.get("email") ?? ""));
  } catch (error) {
    loginError(error instanceof Error ? error.message : "Invalid email.");
  }

  const supabase = await createClient();
  const { error } = await sendOperatorOtp(supabase.auth, email);
  if (error) loginError("Unable to send code. Try again later.");

  await rememberPendingEmail(email);
  redirect("/login?sent=1");
}

export async function verifyEmailOtp(formData: FormData) {
  const email = await pendingEmail();
  if (!email) loginError("Request a new code before verifying.");

  let token: string;
  try {
    token = normalizeEmailOtp(String(formData.get("token") ?? ""));
  } catch (error) {
    loginError(
      error instanceof Error ? error.message : "Invalid code.",
      true,
    );
  }

  const supabase = await createClient();
  const { data, error } = await verifyOperatorOtp(
    supabase.auth,
    email,
    token,
  );
  if (error || !data?.session || !data.user) {
    loginError("Invalid or expired code.", true);
  }

  await clearPendingEmail();
  redirect("/");
}

export async function resendEmailOtp() {
  const email = await pendingEmail();
  if (!email) loginError("Enter your operator email to request a code.");

  const supabase = await createClient();
  const { error } = await sendOperatorOtp(supabase.auth, email);
  if (error) loginError("Unable to resend code. Try again later.", true);

  await rememberPendingEmail(email);
  redirect("/login?sent=1");
}

export async function restartEmailOtp() {
  await clearPendingEmail();
  redirect("/login");
}
