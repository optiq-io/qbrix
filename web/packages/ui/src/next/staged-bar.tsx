import { Layers } from "lucide-react";
import { cn } from "../lib/utils";
import { Button } from "./button";

export type StagedChange = {
  summary: string;
  /** one change shows this alone, so it reads as a full sentence; several show "summary → consequence" */
  consequence: string;
};

export function applyLabel(count: number) {
  if (count === 1) return "Apply";
  if (count === 2) return "Apply both";
  return `Apply all ${count}`;
}

export function StagedBar({
  changes,
  onReview,
  onDiscard,
  onApply,
  label,
  action,
  applying = false,
  canEdit = true,
  className,
}: {
  changes: StagedChange[];
  /** replaces the count, for what isn't a change to something that exists: "New loop" */
  label?: string;
  /** replaces the apply label: "Create draft" */
  action?: string;
  onReview: () => void;
  onDiscard: () => void;
  onApply: () => void;
  applying?: boolean;
  /** false for a person who can't make these changes: the bar is absent */
  canEdit?: boolean;
  className?: string;
}) {
  const count = changes.length;
  if (count === 0 || !canEdit) return null;

  return (
    <section
      aria-label="Staged changes"
      aria-busy={applying}
      className={cn("flex min-h-[46px] shrink-0 items-center gap-3 bg-n-new-bg px-6 py-2", className)}
    >
      <Layers size={14} className="shrink-0 text-n-new-fg" />
      <span className="n-body shrink-0 font-medium tabular-nums text-n-new-fg">
        {label ?? `${count} staged ${count === 1 ? "change" : "changes"}`}
      </span>
      <span aria-hidden className="h-4 w-px shrink-0 bg-n-new-fg/30" />
      <p className="n-body min-w-0 flex-1 whitespace-pre-wrap text-n-text-1">
        {count === 1
          ? changes[0].consequence
          : changes.map((change) => `${change.summary} → ${change.consequence}`).join("   ·   ")}
      </p>
      {count > 1 && (
        <Button variant="quiet" size="sm" onClick={onReview} disabled={applying} className="text-n-text-2">
          Review
        </Button>
      )}
      <Button variant="quiet" size="sm" onClick={onDiscard} disabled={applying} className="text-n-text-2">
        Discard
      </Button>
      <Button size="sm" onClick={onApply} disabled={applying}>
        {applying ? "Applying…" : (action ?? applyLabel(count))}
      </Button>
    </section>
  );
}
