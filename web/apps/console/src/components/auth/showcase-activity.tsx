import { MonoLabel } from "@qbrix/ui/components/mono-label";

// board `APP · Sign in` / Showcase, and `APP · Sign in @ 390` where it stacks
// under the form with the window as a badge.
//
// static illustrative content. nobody is authenticated on this page, so this
// is a worked example on a fictional workspace, not the viewer's own data.

const ALLOCATION = [
  { arm: "social-proof", share: 76.4 },
  { arm: "control", share: 12.1 },
  { arm: "urgency-copy", share: 8.4 },
  { arm: "discount-badge", share: 3.1 },
];

export function ShowcaseActivity() {
  return (
    <div className="flex w-full max-w-[548px] flex-col gap-10">
      <div className="flex items-center justify-between gap-4">
        <MonoLabel tone="faint">While you were away</MonoLabel>
        <MonoLabel tone="faint" className="lg:hidden">
          14 days
        </MonoLabel>
      </div>

      <p className="text-[26px] font-medium leading-[1.3] tracking-[-0.01em] text-text-primary md:text-[30px]">
        checkout-cta moved 76.4% of its traffic to social-proof over 14 days.
      </p>

      <div className="flex flex-col gap-4 rounded-xl bg-bg-panel p-5">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[12px] text-text-secondary">
            checkout-cta
          </span>
          <span className="rounded-full bg-accent-soft px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-accent">
            live
          </span>
        </div>

        <div className="flex flex-col gap-2.5">
          {ALLOCATION.map((row, i) => (
            <div key={row.arm} className="flex items-center gap-3">
              <span className="w-[104px] shrink-0 truncate font-mono text-[11px] text-text-dim">
                {row.arm}
              </span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg-hover">
                <div
                  className={i === 0 ? "h-full rounded-full bg-accent" : "h-full rounded-full bg-bar"}
                  style={{ width: `${row.share}%` }}
                />
              </div>
              <span className="w-[46px] shrink-0 text-right font-mono text-[11px] tabular-nums text-text-secondary">
                {row.share}%
              </span>
            </div>
          ))}
        </div>
      </div>

      <MonoLabel tone="faint" className="hidden lg:inline">
        Last 14 days · Driftwell · Growth plan
      </MonoLabel>
    </div>
  );
}
