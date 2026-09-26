import type { Tone } from "@/components/auth/transactional-card";

// board `APP · Billing outcome`. the radial bloom behind the card is the one
// sanctioned exception to the no-coloured-glow rule, and it exists only here —
// every other transactional state sits on a flat backdrop.
//
// the board's bloom is a 520x500 ellipse in a 520-tall stage at y:-100, against
// a vertically-centred card: centred across, and a little over 100px above the
// card's own centre.
const BLOOM: Partial<Record<Tone, string>> = {
  accent: "#C4F82A12",
  info: "#7AA8EE1A",
  neutral: "#FFFFFF0A",
};

export function OutcomeShell({
  tone,
  children,
}: {
  tone: Tone;
  children: React.ReactNode;
}) {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-bg px-5 py-12">
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 h-[620px] w-[640px] -translate-x-1/2 -translate-y-1/2"
        style={{
          top: "calc(50% - 110px)",
          background: `radial-gradient(50% 50% at 50% 50%, ${BLOOM[tone] ?? "transparent"} 0%, transparent 100%)`,
        }}
      />
      <div className="relative flex w-full max-w-[420px] justify-center">
        {children}
      </div>
    </div>
  );
}
