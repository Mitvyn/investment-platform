export function marketSeriesUnavailableReason(error: { code?: string }): string {
  if (error.code === "42P01" || error.code === "PGRST205") {
    return "Market-series storage is not migrated.";
  }
  return "Market-series query failed. Check authenticated access, then retry.";
}
