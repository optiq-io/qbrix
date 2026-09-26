import { cn } from "../lib/utils";

// the form-level result message. this shape was hand-rolled 15+ times across
// settings, pools, experiments and auth, in two geometries and with the raw
// tailwind red/green rather than the danger/positive tokens.
//
// both geometries ship as sizes because neither is drawn: `sm` is the auth
// stack's mono line, `md` the settings stack's sans block. converging them is
// a page decision, not one to take here.

type BannerTone = "danger" | "positive";
type BannerSize = "sm" | "md";

const TONE: Record<BannerTone, string> = {
  danger: "border-danger/20 bg-danger/10 text-danger",
  positive: "border-positive/20 bg-positive/10 text-positive",
};

const SIZE: Record<BannerSize, string> = {
  sm: "rounded px-3 py-2.5 font-mono text-[11px]",
  md: "rounded-lg px-4 py-3 text-[13px]",
};

type InlineBannerProps = {
  tone?: BannerTone;
  size?: BannerSize;
  children: React.ReactNode;
  className?: string;
};

export function InlineBanner({
  tone = "danger",
  size = "md",
  children,
  className,
}: InlineBannerProps) {
  return (
    <div role="status" className={cn("border", TONE[tone], SIZE[size], className)}>
      {children}
    </div>
  );
}
