type SupabaseConfig = {
  publishableKey: string;
  url: string;
};

export function getSupabaseConfig(): SupabaseConfig {
  const url =
    process.env.IROS_SUPABASE_URL ??
    process.env.NEXT_PUBLIC_SUPABASE_URL ??
    process.env.VITE_SUPABASE_URL;
  const publishableKey =
    process.env.IROS_SUPABASE_PUBLISHABLE_KEY ??
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ??
    process.env.VITE_SUPABASE_PUBLISHABLE_KEY;

  if (!url || !publishableKey) {
    throw new Error("Supabase URL and publishable key are required");
  }

  return { publishableKey, url };
}
