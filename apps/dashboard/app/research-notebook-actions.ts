"use server";

import { redirect } from "next/navigation";

import { addTickerNotebookNote, isCanonicalSecurityKnown } from "../lib/research-notebook";
import { loadSecurityDirectory } from "../lib/securities";
import { createClient } from "../lib/supabase/server";

export async function addResearchNotebookNote(formData: FormData) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  if (error || !data?.claims?.sub) redirect("/login");

  const securityId = String(formData.get("securityId") ?? "").trim();
  const view = String(formData.get("view") ?? "research").trim() || "research";
  const query = new URLSearchParams({ view });
  if (securityId) query.set("security", securityId);

  const directory = await loadSecurityDirectory();
  if (!isCanonicalSecurityKnown(securityId, directory.map((entry) => entry.securityId))) {
    query.set("notebook_error", "security_unauthorized");
    redirect(`/?${query.toString()}`);
  }

  try {
    await addTickerNotebookNote(securityId, String(formData.get("body") ?? ""));
  } catch {
    query.set("notebook_error", "add_failed");
    redirect(`/?${query.toString()}`);
  }
  redirect(`/?${query.toString()}`);
}
