import { cn } from "../lib/utils";

type StatCellProps = {
  label: string;
  value: React.ReactNode;
  delta?: React.ReactNode;
  sub?: React.ReactNode;
  className?: string;
};

// board `01 · Components` / Cell / Stat: label mono 10.5 at 2.2px tracking on
// $text-faint, value mono 24 at -0.6px on $text-primary, 7px between them.
// the label tracking is far wider than the responsive contract's mono label —
// the design carries several mono roles and this is the widest of them.
export function StatCell({ label, value, delta, sub, className }: StatCellProps) {
  return (
    <div className={cn("flex min-w-0 flex-col justify-between gap-[7px]", className)}>
      <span className="font-mono text-[10.5px] uppercase tracking-[0.21em] text-text-faint">
        {label}
      </span>
      <div className="font-mono text-[24px] leading-none tracking-[-0.025em] tabular-nums text-text-primary">
        {value}
      </div>
      {(delta || sub) && (
        <div className="flex items-center gap-2 font-mono text-[11px] text-text-dim">
          {delta}
          {sub}
        </div>
      )}
    </div>
  );
}

type StatStripProps = {
  children: React.ReactNode;
  className?: string;
};

export function StatStrip({ children, className }: StatStripProps) {
  return (
    <div
      className={cn(
        "grid min-h-[100px] divide-x divide-border-subtle rounded-md border border-border-subtle bg-bg-panel",
        className,
      )}
    >
      {children}
    </div>
  );
}
