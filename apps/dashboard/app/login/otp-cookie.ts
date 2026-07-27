const PENDING_EMAIL_MAX_AGE_SECONDS = 10 * 60;
const PENDING_EMAIL_COOKIE_PATH = "/login";

type OtpCookieEnvironment = Record<string, string | undefined>;

export function pendingOtpCookieOptions(
  environment: OtpCookieEnvironment,
) {
  return {
    httpOnly: true,
    maxAge: PENDING_EMAIL_MAX_AGE_SECONDS,
    path: PENDING_EMAIL_COOKIE_PATH,
    sameSite: "lax" as const,
    secure:
      environment.NODE_ENV === "production"
      && environment.IROS_DESKTOP !== "1",
  };
}
