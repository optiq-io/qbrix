import { cn } from "../lib/utils";

// the list skeleton every console page shares — Home, Pools, Event log and the
// experiment Arms tab all draw the same 34px column bar over hairline rows at a
// 28px inset. only the columns differ, which is why this is two thin pieces
// rather than a DataTable that owns the data.

export type Column = {
  label: string;
  /** fixed px width; omit for the column that takes the remaining space */
  width?: number;
  align?: "left" | "right";
  /** opt out of the caps treatment. `α / β` must stay lowercase — uppercasing
      Greek yields `Α / Β`, which are different symbols, not styled ones. */
  preserveCase?: boolean;
};

export function ColumnBar({
  columns,
  gap = 18,
  divideTop = true,
  className,
}: {
  columns: Column[];
  gap?: number;
  /** Arms opens straight into its bar with no head above, so it has no top rule */
  divideTop?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex h-[34px] shrink-0 items-center border-b border-border-subtle px-7",
        divideTop && "border-t",
        className,
      )}
      style={{ gap }}
    >
      {columns.map((col) => (
        <span
          key={col.label}
          className={cn(
            "shrink-0 font-mono text-[11px] tracking-[0.145em] text-text-faint",
            !col.preserveCase && "uppercase",
            col.width === undefined && "min-w-0 flex-1",
            col.align === "right" && "text-right",
          )}
          style={col.width !== undefined ? { width: col.width } : undefined}
        >
          {col.label}
        </span>
      ))}
    </div>
  );
}

export function DataRow({
  height = 68,
  gap = 18,
  href,
  className,
  children,
}: {
  height?: number;
  gap?: number;
  /** rendered by the caller as a Link wrapper; this only carries the geometry */
  href?: never;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex items-center border-b border-border-subtle px-7 transition-colors hover:bg-bg-hover",
        className,
      )}
      style={{ height, gap }}
    >
      {children}
    </div>
  );
}

// a row cell that matches a Column's width and alignment
export function Cell({
  width,
  align,
  clip = true,
  className,
  children,
}: {
  width?: number;
  align?: "left" | "right";
  /** off for a cell holding a popover: `truncate` is `overflow: hidden`, and an
      overflow-menu opens outside the cell box, so it is clipped away entirely */
  clip?: boolean;
  className?: string;
  /** optional so a column can hold a spacer — e.g. a hover-only actions slot */
  children?: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "min-w-0 shrink-0",
        clip && "truncate",
        width === undefined && "flex-1",
        align === "right" && "text-right",
        className,
      )}
      style={width !== undefined ? { width } : undefined}
    >
      {children}
    </div>
  );
}
