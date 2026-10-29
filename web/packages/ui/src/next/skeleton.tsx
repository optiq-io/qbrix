import { cn } from "../lib/utils";

type TextType = "lead" | "support" | "body" | "meta" | "label";

const TYPE: Record<TextType, string> = {
  lead: "n-lead",
  support: "n-support",
  body: "n-body",
  meta: "n-meta",
  label: "n-label",
};

/** a line of text before it arrives: a box exactly one line of `type` high, holding an 8px bar */
export function SkeletonText({
  type = "body",
  width,
  className,
}: {
  type?: TextType;
  width: number;
  className?: string;
}) {
  return (
    <span aria-hidden className={cn(TYPE[type], "flex shrink-0 items-center", className)} style={{ height: "1lh" }}>
      <span className="h-2 max-w-full shrink-0 rounded-n-chip bg-n-fill-2" style={{ width }} />
    </span>
  );
}

/** a region that arrives whole, such as a chart: one quiet block at its final height */
export function SkeletonBlock({ height, className }: { height: number; className?: string }) {
  return <div aria-hidden className={cn("w-full rounded-n-control bg-n-fill-1", className)} style={{ height }} />;
}

/** the object page's four-part header before its data: eyebrow, status line, item and facts.
    a "none yet" header has no item and no facts */
export function SkeletonHeader({ item = true, facts = 4 }: { item?: boolean; facts?: number }) {
  return (
    <div aria-hidden className="flex flex-col gap-4 pb-2">
      <span className="flex h-3.5 items-center">
        <span className="h-2 w-[220px] rounded-n-chip bg-n-fill-2" />
      </span>
      <span className="flex h-[34px] items-center">
        <span className="h-[22px] w-full max-w-[420px] rounded-n-chip bg-n-fill-2" />
      </span>
      {item && (
        <span className="flex h-[42px] flex-col justify-center gap-2">
          <span className="h-3 w-full max-w-[480px] rounded-n-chip bg-n-fill-2" />
          <span className="h-2 w-[140px] rounded-n-chip bg-n-fill-2" />
        </span>
      )}
      {facts > 0 && (
        <span className="flex gap-6 border-t border-n-line-2 pt-4">
          {Array.from({ length: facts }, (_, i) => (
            <span key={i} className="flex h-[50px] flex-1 flex-col justify-center gap-2">
              <span className="h-2 w-[60px] rounded-n-chip bg-n-fill-2" />
              <span className="h-3.5 w-[90px] rounded-n-chip bg-n-fill-2" />
            </span>
          ))}
        </span>
      )}
    </div>
  );
}

export type SkeletonColumn = {
  /** the cell's width in px; omit for the column that fills */
  width?: number;
  /** bar widths, one per line the cell will hold */
  lines: number[];
};

/** a list before its rows arrive: the column bar, then rows holding as many lines as the real ones */
export function SkeletonList({ columns, rows = 4 }: { columns: SkeletonColumn[]; rows?: number }) {
  return (
    <div aria-hidden className="flex flex-col">
      <div className="flex gap-6 border-b border-n-line-2 pb-2">
        {columns.map((column, i) => (
          <Cell key={i} width={column.width}>
            <SkeletonText type="meta" width={Math.round((column.width ?? 336) * 0.7)} />
          </Cell>
        ))}
      </div>
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="flex items-center gap-6 border-b border-n-line-2 py-3">
          {columns.map((column, i) => (
            <Cell key={i} width={column.width} className="flex flex-col gap-1">
              {column.lines.map((width, line) => (
                <SkeletonText key={line} type={line === 0 ? "body" : "meta"} width={width} />
              ))}
            </Cell>
          ))}
        </div>
      ))}
    </div>
  );
}

/** the properties rail before its data: per group, a label and that many label · value rows */
export function SkeletonRail({ groups }: { groups: number[] }) {
  return (
    <div aria-hidden className="flex flex-col gap-6">
      {groups.map((rows, group) => (
        <div key={group} className="flex flex-col gap-3">
          <SkeletonText type="meta" width={28} />
          {Array.from({ length: rows }, (_, row) => (
            <div key={row} className="flex items-center justify-between gap-2">
              <SkeletonText width={[22, 24, 29, 27, 34][(group + row) % 5]} />
              <SkeletonText width={[17, 25, 47, 60, 37][(group * 2 + row) % 5]} />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function Cell({ width, className, children }: { width?: number; className?: string; children: React.ReactNode }) {
  return (
    <div className={cn(width ? "shrink-0" : "min-w-0 flex-1", className)} style={width ? { width } : undefined}>
      {children}
    </div>
  );
}
