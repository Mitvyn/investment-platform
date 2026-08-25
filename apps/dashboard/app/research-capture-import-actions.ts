"use server";

import { redirect } from "next/navigation";

import {
  importResearchCapture,
  importResearchCaptureUpload,
} from "../lib/research-capture-import";
import { isCanonicalSecurityKnown } from "../lib/research-notebook";
import { loadSecurityDirectory } from "../lib/securities";
import { createClient } from "../lib/supabase/server";

export async function importResearchCaptureAction(formData: FormData) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  const operatorId = data?.claims?.sub;
  if (error || !data?.claims || typeof operatorId !== "string") redirect("/login");

  const securityId = String(formData.get("securityId") ?? "").trim();
  const view = String(formData.get("view") ?? "research").trim() || "research";
  const query = new URLSearchParams({ view });
  if (securityId) query.set("security", securityId);

  const directory = await loadSecurityDirectory();
  const security = directory.find((entry) => entry.securityId === securityId);
  if (
    !isCanonicalSecurityKnown(securityId, directory.map((entry) => entry.securityId)) ||
    !security
  ) {
    query.set("capture_import_error", "security_unauthorized");
    redirect(`/?${query.toString()}`);
  }

  try {
    const archive = formData.get("captureArchive");
    if (typeof Blob !== "undefined" && archive instanceof Blob) {
      await importResearchCaptureUpload({
        archive,
        cik: security.cik,
        confirmEmbeddedIssuerHosts:
          String(formData.get("confirmEmbeddedIssuerHosts") ?? "") === "on",
        issuerName: security.companyName,
        operatorId,
        primaryListingExchange: security.primaryListingExchange,
        securityId,
      });
    } else {
      await importResearchCapture({
        archivePath: String(formData.get("archivePath") ?? ""),
        asOfCutoff: String(formData.get("captureAsOfCutoff") ?? ""),
        cik: security.cik,
        issuerName: security.companyName,
        operatorId,
        primaryListingExchange: security.primaryListingExchange,
        securityId,
        trustedIssuerHosts: String(formData.get("trustedIssuerHosts") ?? "")
          .split(",")
          .map((host) => host.trim())
          .filter((host) => host.length > 0),
      });
    }
  } catch {
    query.set("capture_import_error", "import_failed");
    redirect(`/?${query.toString()}`);
  }
  query.set("capture_import", "accepted");
  redirect(`/?${query.toString()}`);
}
