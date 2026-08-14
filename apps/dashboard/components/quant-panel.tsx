import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Quant is a separate product feature. Architecture decision 0001 keeps its
 * datasets, features, backtests, and signals in their own bounded context: they
 * may share canonical `security_id` but must never reach Research evidence,
 * readiness, or thesis state. This placeholder exists so the boundary is
 * visible in the product before any Quant data lands.
 */
export function QuantPanel() {
  const planned: Array<{ title: string; detail: string }> = [
    {
      title: "Datasets and features",
      detail: "Point-in-time bars, quotes, and derived features.",
    },
    {
      title: "Backtests",
      detail: "Time-bounded, statistically validated strategy evaluation.",
    },
    {
      title: "Paper signals",
      detail: "Simulated-trading observations with no execution authority.",
    },
    {
      title: "Performance and risk",
      detail: "Attribution and exposure for validated signals.",
    },
  ];

  return (
    <>
      <Card className="mt-5">
        <CardHeader>
          <p className="font-mono text-[11px] font-medium tracking-[0.14em] text-primary uppercase">
            Quant research and signals
          </p>
          <CardTitle className="mt-2">Not yet available</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Quant is a separate product feature with its own bounded context. It
            shares canonical security identity and nothing else — Quant datasets
            and signals cannot enter Research evidence, readiness, or thesis
            state, and Research artifacts do not feed Quant.
          </p>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            {planned.map((item) => (
              <div
                className="rounded-lg border border-dashed border-border px-4 py-3"
                key={item.title}
              >
                <p className="text-sm font-medium">{item.title}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.detail}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-5 text-xs text-muted-foreground">
            Live order execution stays outside this feature until a separately
            approved execution contract, threat model, and confirmation flow
            exist.
          </p>
        </CardContent>
      </Card>
    </>
  );
}
