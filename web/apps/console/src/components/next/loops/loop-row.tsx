import { ActorMark, LoopRef, actorName } from "@qbrix/ui/next/entity";
import type { ListColumn } from "@qbrix/ui/next/list";
import { StateBadge, StateDot } from "@qbrix/ui/next/state";
import type { LoopListItem } from "@/lib/api/types";
import { signedPercent } from "@/lib/loop/fact";
import { latestEvent, listStatus, rowTime, shareSegments, toListActor } from "@/lib/loop/list";
import { duration, type Pause } from "@/lib/loop/pause";
import { ShareBar } from "./share-bar";

function Subject({ loop }: { loop: LoopListItem }) {
  const status = listStatus(loop);
  return (
    <div className="flex items-start gap-3">
      <span className="flex h-5 w-[15px] shrink-0 items-center justify-center">
        {status === "paused" ? (
          <StateDot state="part" />
        ) : status === "draft" ? (
          <span aria-hidden className="size-1.5 rounded-full bg-n-line" />
        ) : (
          <StateDot state="ok" />
        )}
      </span>
      <div className="flex min-w-0 flex-col">
        <span className="n-body flex min-w-0 items-center gap-2">
          <LoopRef name={loop.name} className="truncate" />
          {status === "paused" && <StateBadge state="part">Paused</StateBadge>}
          {status === "draft" && <StateBadge>Draft</StateBadge>}
          {status === "warming_up" && <StateBadge>Warming up</StateBadge>}
        </span>
        {loop.latest_change && <span className="n-body truncate text-n-text-2">{latestEvent(loop.latest_change)}</span>}
      </div>
    </div>
  );
}

function Lift({ loop, pause, now }: { loop: LoopListItem; pause: Pause | undefined; now: number }) {
  if (loop.state === "paused") {
    return (
      <span className="n-body font-medium text-n-part-fg">
        paused{pause ? ` · ${duration(now - pause.at)}` : ""}
      </span>
    );
  }
  const lift = loop.results?.lift;
  if (lift === null || lift === undefined) return null;
  return (
    <span className="n-body font-medium text-n-text-1">
      {signedPercent(lift)}
      {loop.results?.early && " · early"}
    </span>
  );
}

function LastChange({ loop, now }: { loop: LoopListItem; now: number }) {
  const change = loop.latest_change;
  if (!change) return <span className="n-label font-normal text-n-text-3">—</span>;
  const actor = toListActor(change);
  return (
    <div className="flex items-center gap-2">
      <ActorMark actor={actor} size={20} />
      <div className="flex min-w-0 flex-col">
        <span className="n-meta truncate text-n-text-1">{actorName(actor)}</span>
        <span className="n-label font-normal text-n-text-3">{rowTime(change.at, now)}</span>
      </div>
    </div>
  );
}

export function loopColumns(pauses: Map<string, Pause>, now: number): ListColumn<LoopListItem>[] {
  return [
    { key: "loop", label: "Loop", render: (loop) => <Subject loop={loop} /> },
    {
      key: "share",
      label: "Share now",
      width: "150px",
      render: (loop) => <ShareBar segments={shareSegments(loop)} frozen={loop.state === "paused"} />,
    },
    {
      key: "lift",
      label: "vs even split",
      width: "140px",
      render: (loop) => (
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="n-label truncate font-n-mono font-normal text-n-text-2">{loop.metric.name}</span>
          <Lift loop={loop} pause={pauses.get(loop.id)} now={now} />
        </div>
      ),
    },
    { key: "last", label: "Last change", width: "110px", render: (loop) => <LastChange loop={loop} now={now} /> },
  ];
}
