import { Badge } from "@/components/ui/badge";
import { presentStatusStrip, type StatusStripInput } from "@/lib/status-strip-model";

export { presentStatusStrip } from "@/lib/status-strip-model";

export function StatusStrip(input: StatusStripInput) {
  return (
    <div
      aria-label="Workspace status"
      className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 lg:grid-cols-5"
    >
      {presentStatusStrip(input).map((item) => (
        <div className="flex items-center justify-between gap-3 bg-card px-4 py-3" key={item.label}>
          <span className="text-xs text-muted-foreground">{item.label}</span>
          <Badge variant={item.tone}>{item.value}</Badge>
        </div>
      ))}
    </div>
  );
}
