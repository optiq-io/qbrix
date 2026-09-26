import { Boxes } from "lucide-react";

// experiments empty-state mark — four stacked allocation bars (one accent
// segment each). echoes the AllocationBar visual that appears on every
// populated experiment row. dimensions are inlined so the icon renders
// pixel-perfect regardless of how tailwind's content scan behaves.
const expRows: number[][] = [
  [44, 28, 18, 10],
  [38, 30, 22, 12, 8],
  [50, 26, 16, 10],
  [40, 30, 20, 12, 8],
];

// a descending ramp, so it maps to a monotonic run of tokens rather than one
// repeated tint: the winner, then inert data, then the two border weights.
const expSegmentColors = [
  "var(--color-accent)",
  "var(--color-border-strong)",
  "var(--color-bar)",
  "var(--color-border)",
  "var(--color-border-subtle)",
];

export function ExperimentsEmptyIcon() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 7,
      }}
    >
      {expRows.map((widths, i) => (
        <div
          key={i}
          style={{ display: "flex", gap: 2, height: 5 }}
        >
          {widths.map((w, j) => (
            <div
              key={j}
              style={{
                width: w,
                height: 5,
                borderRadius: 1.5,
                backgroundColor:
                  expSegmentColors[Math.min(j, expSegmentColors.length - 1)],
              }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

// pools empty-state mark — 2x2 cluster of the same pool tile that appears
// inside each populated pool row. one tile uses the accent fill. inline
// styles keep the grid honoring 36x36 tiles + 8px gap exactly as drawn.
const poolTiles: boolean[] = [false, true, false, false];

export function PoolsEmptyIcon() {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(2, 36px)",
        gridAutoRows: "36px",
        gap: 8,
      }}
    >
      {poolTiles.map((accent, i) => (
        <div
          key={i}
          style={{
            width: 36,
            height: 36,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 7,
            border: `1px solid ${
              accent
                ? "color-mix(in oklab, var(--color-accent) 60%, transparent)"
                : "var(--color-border-subtle)"
            }`,
            backgroundColor: accent
              ? "var(--color-accent-soft)"
              : "var(--color-bg-bg-panel)",
          }}
        >
          <Boxes
            size={16}
            color={accent ? "var(--color-accent)" : "var(--color-text-dim)"}
          />
        </div>
      ))}
    </div>
  );
}

// event-log empty-state mark — the stream as a run of spikes, bottom-aligned
// so it reads as throughput over time rather than a bar chart. board
// `APP · Empty, loading & error states` / EVENT LOG: 9-wide bars at r3, heights
// 14/24/36/22/12, gap 6, no accent — unlike the pools and gates marks, this one
// is deliberately inert, because an empty stream has no winner to point at.
const streamBars = [14, 24, 36, 22, 12];

export function EventsEmptyIcon() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "center",
        gap: 6,
        height: 46,
      }}
    >
      {streamBars.map((h, i) => (
        <div
          key={i}
          style={{
            width: 9,
            height: h,
            borderRadius: 3,
            backgroundColor: "var(--color-bg-panel)",
          }}
        />
      ))}
    </div>
  );
}
