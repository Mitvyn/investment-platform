import { NextResponse } from "next/server";

import { createClient } from "../../../lib/supabase/server";

function safeRedirectUrl(path: string | null, origin: string): URL {
  const target = new URL(path || "/", origin);
  return target.origin === origin ? target : new URL("/", origin);
}

export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const code = requestUrl.searchParams.get("code");

  if (!code) {
    return NextResponse.redirect(
      new URL("/login?error=Missing%20authentication%20code", requestUrl.origin),
    );
  }

  const supabase = await createClient();
  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) {
    return NextResponse.redirect(
      new URL(`/login?error=${encodeURIComponent(error.message)}`, requestUrl.origin),
    );
  }

  return NextResponse.redirect(
    safeRedirectUrl(requestUrl.searchParams.get("next"), requestUrl.origin),
  );
}
