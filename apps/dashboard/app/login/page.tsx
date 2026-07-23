import { redirect } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { createClient } from "../../lib/supabase/server";
import {
  requestEmailOtp,
  resendEmailOtp,
  restartEmailOtp,
  verifyEmailOtp,
} from "./actions";
import {
  presentLoginFeedback,
  type LoginSearchParams,
} from "./login-presentation";

type LoginPageProps = {
  searchParams: Promise<LoginSearchParams>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  if (data?.claims) {
    redirect("/");
  }

  const params = await searchParams;
  const feedback = presentLoginFeedback(params);
  const codeRequested = params.sent === "1";

  return (
    <main className="grid min-h-svh place-items-center px-4 py-8 sm:px-8">
      <Card
        aria-labelledby="login-title"
        className="w-full max-w-[620px] overflow-hidden bg-card/95"
      >
        <CardHeader className="gap-5 p-7 sm:p-10 lg:p-14">
          <p className="font-mono text-[11px] font-medium tracking-[0.12em] text-evidence uppercase">
            Private operator access
          </p>
          <CardTitle
            className="max-w-full text-balance break-words font-serif text-[clamp(2.5rem,12vw,6.5rem)] leading-[0.88] font-medium tracking-[-0.055em] [overflow-wrap:anywhere]"
            id="login-title"
          >
            Investment Research OS
          </CardTitle>
          <CardDescription className="max-w-[35rem] text-base leading-7">
            {codeRequested
              ? "Enter the six-digit code sent to your operator email."
              : "Enter operator email. Supabase sends a six-digit sign-in code."}
          </CardDescription>
        </CardHeader>

        <CardContent className="grid gap-6 px-7 pb-7 sm:px-10 sm:pb-10 lg:px-14 lg:pb-14">
          {feedback.map((item) => (
            <Alert key={item.role} role={item.role} variant={item.tone}>
              {item.message}
            </Alert>
          ))}

          {codeRequested ? (
            <div className="grid gap-4">
              <form action={verifyEmailOtp} className="grid gap-4">
                <div className="grid gap-2">
                  <Label
                    className="font-mono text-[11px] tracking-[0.08em] text-evidence uppercase"
                    htmlFor="token"
                  >
                    Verification code
                  </Label>
                  <Input
                    autoComplete="one-time-code"
                    id="token"
                    inputMode="numeric"
                    maxLength={6}
                    minLength={6}
                    name="token"
                    pattern="[0-9]{6}"
                    placeholder="000000"
                    required
                    type="text"
                  />
                </div>
                <Button className="w-fit" type="submit">
                  Verify code
                </Button>
              </form>

              <div className="flex flex-wrap gap-2">
                <form action={resendEmailOtp}>
                  <Button size="sm" type="submit" variant="outline">
                    Send new code
                  </Button>
                </form>
                <form action={restartEmailOtp}>
                  <Button size="sm" type="submit" variant="ghost">
                    Use different email
                  </Button>
                </form>
              </div>
            </div>
          ) : (
            <form action={requestEmailOtp} className="grid gap-4">
              <div className="grid gap-2">
                <Label
                  className="font-mono text-[11px] tracking-[0.08em] text-evidence uppercase"
                  htmlFor="email"
                >
                  Operator email
                </Label>
                <Input
                  autoComplete="email"
                  id="email"
                  maxLength={254}
                  name="email"
                  placeholder="you@example.com"
                  required
                  type="email"
                />
              </div>
              <Button className="w-fit" type="submit">
                Send sign-in code
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
