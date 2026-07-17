export type EvidenceTrace = {
  ticker: string;
  companyName: string;
  researchRunId: string;
  runStatus: "completed";
  sourceProvider: "sec";
  sourceTitle: string;
  filingForm: string;
  filedAt: string;
  periodEnd: string;
  accessionNumber: string;
  sourceUrl: string;
  retrievedAt: string;
  locator: string;
  passage: string;
  passageSha256: string;
  claim: string;
  verificationState:
    | "unverified"
    | "supported"
    | "contradicted"
    | "unclear"
    | "invalidated"
    | "stale";
};
