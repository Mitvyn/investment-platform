import { Badge } from "@/components/ui/badge";
import {
  presentEvidenceGap,
  type EvidenceGapState,
} from "@/lib/evidence-gap-row-model";

export function EvidenceGapRow({
  detail,
  label,
  state = "missing",
}: {
  detail: string;
  label: string;
  state?: EvidenceGapState;
}) {
  const presentation = presentEvidenceGap(label, state);
  return (
    <div className="flex items-center justify-between gap-3 border-t border-border py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium">{presentation.label}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{detail}</p>
      </div>
      <Badge variant={state === "gated" ? "attention" : "outline"}>
        {presentation.stateLabel}
      </Badge>
    </div>
  );
}
