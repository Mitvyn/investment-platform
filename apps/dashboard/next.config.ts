import type { NextConfig } from "next";

const supabaseUrl =
  process.env.IROS_SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabasePublishableKey =
  process.env.IROS_SUPABASE_PUBLISHABLE_KEY ??
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

const nextConfig: NextConfig = {
  // Both values are public client configuration. Desktop builds embed them so
  // double-click launch never depends on shell environment.
  env:
    supabaseUrl && supabasePublishableKey
      ? {
          IROS_SUPABASE_PUBLISHABLE_KEY: supabasePublishableKey,
          IROS_SUPABASE_URL: supabaseUrl,
        }
      : undefined,
  experimental: {
    serverActions: {
      bodySizeLimit: "25mb",
    },
  },
  reactStrictMode: true,
};

export default nextConfig;
