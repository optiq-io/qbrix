import { HoverCard } from "@qbrix/ui/next/hover-card";
import { cn } from "@qbrix/ui/lib/utils";
import type { ShareSegment } from "@/lib/loop/list";

const TONE: Record<ShareSegment["rank"], string> = {
  0: "bg-n-ink",
  1: "bg-n-viz-2",
  2: "bg-n-viz-3",
  3: "bg-n-viz-track",
};

const FROZEN_TONE: Record<ShareSegment["rank"], string> = {
  0: "bg-n-viz-2",
  1: "bg-n-viz-3",
  2: "bg-n-viz-track",
  3: "bg-n-viz-track",
};

const percent = (share: number) => `${Math.round(share * 100)}%`;

function Bar({ segments, frozen }: { segments: ShareSegment[]; frozen: boolean }) {
  return (
    <span className="flex h-1.5 w-full gap-0.5 overflow-hidden rounded-[3px]">
      {segments.map((segment) => (
        <span
          key={segment.key}
          className={(frozen ? FROZEN_TONE : TONE)[segment.rank]}
          style={{ flex: `${segment.share} 1 0` }}
        />
      ))}
    </span>
  );
}

export function ShareBar({ segments, frozen }: { segments: ShareSegment[] | null; frozen: boolean }) {
  if (!segments) return <span className="n-label font-normal text-n-text-3">—</span>;

  const [lead] = segments;
  const others = segments.find((segment) => segment.rank === 3);
  const label = `${percent(lead.share)} ${lead.name}${frozen ? " · frozen" : ""}`;

  return (
    <div className="flex flex-col gap-1">
      {others ? (
        <HoverCard
          trigger={
            <button
              type="button"
              aria-label={`Share of decisions, ${label}, and ${others.members.length} others`}
              className="-my-1 flex w-full rounded-n-chip py-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-n-ink"
            >
              <Bar segments={segments} frozen={frozen} />
            </button>
          }
        >
          {others.members.map((member) => (
            <span key={member.name} className="n-meta flex justify-between gap-4 text-n-text-2">
              <span>{member.name}</span>
              <span className="tabular-nums">{percent(member.share)}</span>
            </span>
          ))}
        </HoverCard>
      ) : (
        <Bar segments={segments} frozen={frozen} />
      )}
      <span className={cn("n-label truncate font-normal", frozen ? "text-n-text-3" : "text-n-text-2")}>{label}</span>
    </div>
  );
}
