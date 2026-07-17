import { redirect } from "next/navigation";

import { createClient } from "../../lib/supabase/server";
import { requestMagicLink } from "./actions";

type LoginPageProps = {
  searchParams: Promise<{
    error?: string;
    sent?: string;
  }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  if (data?.claims) {
    redirect("/");
  }

  const params = await searchParams;

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <p className="eyebrow">Private operator access</p>
        <h1>Investment Research OS</h1>
        <p className="auth-copy">
          Enter operator email. Supabase sends one-time sign-in link.
        </p>

        {params.sent === "1" ? (
          <p className="auth-message success">
            Link sent. Open email on this device to continue.
          </p>
        ) : null}
        {params.error ? (
          <p className="auth-message error">{params.error}</p>
        ) : null}

        <form action={requestMagicLink} className="auth-form">
          <label htmlFor="email">Operator email</label>
          <input
            autoComplete="email"
            id="email"
            name="email"
            placeholder="you@example.com"
            required
            type="email"
          />
          <button type="submit">Send sign-in link</button>
        </form>
      </section>
    </main>
  );
}
