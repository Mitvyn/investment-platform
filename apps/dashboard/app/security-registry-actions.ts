"use server";

import { redirect } from "next/navigation";

import {
  addDesktopSecurityTicker,
  importMoomooSecurityTickers,
} from "../lib/moomoo-desktop";
import { createClient } from "../lib/supabase/server";

function returnToSettings(formData: FormData, error?: string): never {
  const security = String(formData.get("securityId") ?? "").trim();
  const query = new URLSearchParams({ view: "settings" });
  if (security) query.set("security", security);
  if (error) query.set("security_registry_error", error);
  redirect(`/?${query.toString()}`);
}

async function requireOperator() {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  if (error || !data?.claims?.sub) redirect("/login");
}

export async function addDesktopSecurity(formData: FormData) {
  await requireOperator();
  try {
    await addDesktopSecurityTicker(String(formData.get("ticker") ?? ""));
  } catch {
    returnToSettings(formData, "add_failed");
  }
  returnToSettings(formData);
}

export async function importMoomooSecurities(formData: FormData) {
  await requireOperator();
  try {
    await importMoomooSecurityTickers();
  } catch {
    returnToSettings(formData, "import_failed");
  }
  returnToSettings(formData);
}
