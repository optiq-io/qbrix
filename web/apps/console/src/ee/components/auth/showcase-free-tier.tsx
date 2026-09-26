import { MonoLabel } from "@qbrix/ui/components/mono-label";

// board `APP · Register` / Showcase.
//
// mirrors PLAN_LIMITS["free"] in svc/proxy/src/proxysvc/mod/auth/scope.py.
// register is pre-auth and nothing publishes the plan matrix unauthenticated,
// so these are the one copy the console cannot resolve at runtime — change
// both together. "All 16" is the policy count in qbrixcore: 9 stochastic,
// 4 contextual, 3 adversarial.
const FREE_TIER = [
  ["Selections", "100,000 / month"],
  ["Active experiments", "3"],
  ["Seats", "3"],
  ["API keys", "2"],
  ["Strategies", "All 16"],
];

export function ShowcaseFreeTier() {
  return (
    <div className="flex w-full max-w-[548px] flex-col gap-8">
      <MonoLabel tone="faint">The free tier</MonoLabel>

      <div className="flex flex-col gap-5">
        <p className="text-[26px] font-medium leading-[1.3] tracking-[-0.01em] text-text-primary md:text-[30px]">
          Free covers your first real experiment.
        </p>
        <p className="text-[14.5px] leading-[1.6] text-text-dim">
          100,000 selections is roughly what one meaningful experiment costs to
          run. That is the point — you should be able to prove this works before
          you pay for it.
        </p>
      </div>

      <div className="flex flex-col rounded-xl bg-bg-panel px-5">
        {FREE_TIER.map(([label, value], i) => (
          <div
            key={label}
            className={
              i === 0
                ? "flex items-center justify-between py-3.5"
                : "flex items-center justify-between border-t border-border-subtle py-3.5"
            }
          >
            <span className="text-[13.5px] text-text-dim">{label}</span>
            <span className="font-mono text-[13px] tabular-nums text-text-primary">
              {value}
            </span>
          </div>
        ))}
      </div>

      <p className="text-[13px] leading-[1.6] text-text-faint">
        No card required. Upgrade when you outgrow it — never before.
      </p>
    </div>
  );
}
