export type LoginSearchParams = {
  error?: string;
  sent?: string;
};

export type LoginFeedback = {
  message: string;
  role: "alert" | "status";
  tone: "destructive" | "verified";
};

export function presentLoginFeedback(
  params: LoginSearchParams,
): LoginFeedback[] {
  const feedback: LoginFeedback[] = [];

  if (params.sent === "1") {
    feedback.push({
      message: "Code sent. Enter the six-digit code from your email.",
      role: "status",
      tone: "verified",
    });
  }
  if (params.error) {
    feedback.push({
      message: params.error,
      role: "alert",
      tone: "destructive",
    });
  }

  return feedback;
}
