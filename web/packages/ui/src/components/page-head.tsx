import { cn } from "../lib/utils";

// every console page opens the same way: a 26px title with an optional line of
// meta under it, a primary action opposite, and a 28px inset. the inset is the
// console's page gutter and is constant across every board.
//
// there is no card. content sits on $bg and is separated by hairlines — see
// `00 · Foundations` / Surfaces & ink, where bg-panel is a *panel*, never the
// ground under a page.
export function PageHead({
  title,
  adornments,
  meta,
  action,
  className,
}: {
  title: React.ReactNode;
  /** status chips set inline beside the title, as on the experiment boards —
      `meta` is the line *below* it and the two are not interchangeable */
  adornments?: React.ReactNode;
  meta?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-end justify-between gap-6 px-7 pb-5 pt-6",
        className,
      )}
    >
      <div className="flex min-w-0 flex-col gap-[7px]">
        <div className="flex min-w-0 items-center gap-3.5">
          <h1 className="truncate text-[26px] font-semibold tracking-[-0.027em] text-text-primary">
            {title}
          </h1>
          {adornments}
        </div>
        {meta && <p className="truncate text-[15px] text-text-dim">{meta}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

// the smaller head that opens a section *within* a page — 17px, with an
// optional action on the right.
export function SectionHead({
  title,
  action,
  className,
}: {
  title: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-4 px-7 pb-3.5 pt-5",
        className,
      )}
    >
      <h2 className="text-[17px] font-semibold text-text-primary">{title}</h2>
      {action}
    </div>
  );
}
