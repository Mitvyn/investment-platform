type AuthResult = {
  data?: {
    session?: unknown;
    user?: unknown;
  };
  error: { message: string } | null;
};

export type EmailOtpAuth = {
  signInWithOtp(request: {
    email: string;
    options: { shouldCreateUser: false };
  }): Promise<AuthResult>;
  verifyOtp(request: {
    email: string;
    token: string;
    type: "email";
  }): Promise<AuthResult>;
};

export function normalizeOperatorEmail(value: string): string {
  const email = value.trim().toLowerCase();
  if (
    email.length > 254
    || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
  ) {
    throw new TypeError("Enter a valid operator email.");
  }
  return email;
}

export function normalizeEmailOtp(value: string): string {
  const token = value.trim();
  if (!/^\d{6}$/.test(token)) {
    throw new TypeError("Enter the six-digit code.");
  }
  return token;
}

export async function sendOperatorOtp(
  auth: EmailOtpAuth,
  email: string,
): Promise<AuthResult> {
  return auth.signInWithOtp({
    email,
    options: { shouldCreateUser: false },
  });
}

export async function verifyOperatorOtp(
  auth: EmailOtpAuth,
  email: string,
  token: string,
): Promise<AuthResult> {
  return auth.verifyOtp({ email, token, type: "email" });
}
