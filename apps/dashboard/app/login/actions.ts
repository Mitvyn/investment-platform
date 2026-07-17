"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { createClient } from "../../lib/supabase/server";

function loginOrigin(originHeader: string | null): string {
  const configured = process.env.IROS_SITE_URL;
  if (configured) {
    return new URL(configured).origin;
  }

  if (originHeader) {
    const origin = new URL(originHeader);
    if (origin.hostname === "127.0.0.1" || origin.hostname === "localhost") {
      return origin.origin;
    }
  }

  return "http://localhost:3000";
}

export async function requestMagicLink(formData: FormData) {
  const email = String(formData.get("email") ?? "")
    .trim()
    .toLowerCase();
  if (!email || !email.includes("@")) {
    redirect("/login?error=Enter%20a%20valid%20email");
  }

  const requestHeaders = await headers();
  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: {
      emailRedirectTo: `${loginOrigin(requestHeaders.get("origin"))}/auth/callback`,
      shouldCreateUser: false,
    },
  });

  if (error) {
    redirect(`/login?error=${encodeURIComponent(error.message)}`);
  }

  redirect("/login?sent=1");
}
