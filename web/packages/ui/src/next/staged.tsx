import { GitCommitHorizontal } from "lucide-react";
import { cn } from "../lib/utils";
import { StateBadge } from "./state";

/** marks an edit that waits on your Apply, where a whole frame would be too much: a row in a table */
export function StagedTag({ className }: { className?: string }) {
  return (
    <StateBadge state="new" className={className}>
      Staged
    </StateBadge>
  );
}

/** a field holding a staged edit */
export function Staged({
  label,
  note,
  className,
  children,
}: {
  label: string;
  /** what it was, and what that means: "Was: everyone." */
  note?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("flex flex-col gap-2 rounded-n-panel border border-n-new-fg bg-n-fill-1 px-4 py-3", className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="n-label text-n-text-3">{label}</span>
        <StagedTag />
      </div>
      {children}
      {note && <p className="n-meta text-n-new-fg">{note}</p>}
    </div>
  );
}

/** what the page becomes once everything staged applies: "When both apply: …" */
export function StagedPreview({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("flex items-center gap-2 rounded-n-control bg-n-fill-1 px-3 py-2", className)}>
      <GitCommitHorizontal size={13} className="shrink-0 text-n-new-fg" />
      <p className="n-meta min-w-0 text-n-new-fg">{children}</p>
    </div>
  );
}

/** what an action will do, beside the action: launching a draft */
export function Consequence({
  title,
  field,
  action,
  className,
  children,
}: {
  title: string;
  /** asked for before the action, such as a reason. the action lines up with its foot */
  field?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={cn("flex gap-4 rounded-n-panel bg-n-bg p-4", field ? "items-end" : "items-center", className)}>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="n-body font-medium text-n-text-1">{title}</p>
        {children && <p className="n-meta text-n-text-2">{children}</p>}
        {field && <div className="mt-2">{field}</div>}
      </div>
      {action}
    </div>
  );
}
