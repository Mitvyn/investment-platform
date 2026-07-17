import type { EvidenceTrace } from "@iros/types";

import { createClient } from "./supabase/server";

type EvidenceRow = {
  ticker: string;
  company_name: string;
  research_run_id: string;
  run_status: "completed";
  source_provider: "sec";
  source_title: string;
  filing_form: string;
  filed_at: string;
  period_end: string;
  accession_number: string;
  source_url: string;
  retrieved_at: string;
  locator: string;
  passage_text: string;
  passage_sha256: string;
  claim_text: string;
  verification_state: EvidenceTrace["verificationState"];
};

export type EvidenceResult = {
  trace: EvidenceTrace | null;
};

function mapRow(row: EvidenceRow): EvidenceTrace {
  return {
    ticker: row.ticker,
    companyName: row.company_name,
    researchRunId: row.research_run_id,
    runStatus: row.run_status,
    sourceProvider: row.source_provider,
    sourceTitle: row.source_title,
    filingForm: row.filing_form,
    filedAt: row.filed_at,
    periodEnd: row.period_end,
    accessionNumber: row.accession_number,
    sourceUrl: row.source_url,
    retrievedAt: row.retrieved_at,
    locator: row.locator,
    passage: row.passage_text,
    passageSha256: row.passage_sha256,
    claim: row.claim_text,
    verificationState: row.verification_state,
  };
}

export async function loadEvidenceTrace(
  ticker: string,
): Promise<EvidenceResult> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_claim_evidence_trace")
    .select(
      "ticker,company_name,research_run_id,run_status,source_provider,source_title,filing_form,filed_at,period_end,accession_number,source_url,retrieved_at,locator,passage_text,passage_sha256,claim_text,verification_state",
    )
    .eq("ticker", ticker.toUpperCase())
    .order("filed_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (error) {
    throw new Error(`Evidence API failed: ${error.message}`);
  }

  return {
    trace: data ? mapRow(data as EvidenceRow) : null,
  };
}
