"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { ArrowDownRight, Bot, Cpu, GitPullRequest, User } from "lucide-react";
import { cn } from "../lib/utils";
import type { Actor } from "./entity";
import { HoverCard } from "./hover-card";
import { axisLabels, MAX_COLUMNS, pickInterval } from "./interval";
import { LiveNumber } from "./live-number";
import { useFrozen } from "./offline";
import { PANEL } from "./overlay";
import { Segmented } from "./segmented";
import {
  bandShares,
  columnRects,
  columnTotal,
  mergeColumns,
  mergeTween,
  rankBands,
  type ShareBand,
  type ShareColumn,
  type ShareOption,
} from "./share";

export { pickInterval };
export type { ShareColumn, ShareOption };

export type ShareRange = "24h" | "7d" | "cycle";

export type SharePin = {
  /** when the change happened; the pin lands in the column that holds it */
  at: number;
  entryId: string;
  actor: Actor;
  title: string;
  /** already formatted: "all → mobile · 4 Oct · share 41% → 58%" */
  detail?: string;
};

const PLOT_HEIGHT = 132;
const COLUMN_GAP = 2;
const PIN_LANE_HEIGHT = 62;
const PIN_SIZE = 16;
const PIN_FAN = 10;

const RANGES: { value: ShareRange; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "cycle", label: "Cycle" },
];

const TONE: Record<ShareBand["rank"], string> = {
  0: "fill-n-ink",
  1: "fill-n-viz-2",
  2: "fill-n-viz-3",
  3: "fill-n-viz-track",
};

const FROZEN_TONE: Record<ShareBand["rank"], string> = {
  0: "fill-n-viz-2",
  1: "fill-n-viz-3",
  2: "fill-n-viz-track",
  3: "fill-n-viz-track",
};

const percent = (share: number) => `${Math.round(share * 100)}%`;
const easeOut = (t: number) => 1 - (1 - t) ** 3;

function PinIcon({ actor }: { actor: Actor }) {
  if (actor.kind === "connection") return <Bot size={9} />;
  if (actor.kind === "github") return <GitPullRequest size={9} />;
  if (actor.kind === "qbrix") return <Cpu size={9} />;
  return <User size={9} />;
}

function Pin({
  pin,
  x,
  flip,
  animated,
  onPin,
}: {
  pin: SharePin;
  x: number;
  flip: boolean;
  animated: boolean;
  onPin?: (entryId: string) => void;
}) {
  return (
    <div
      className={cn(
        "group absolute bottom-0 flex flex-col items-center hover:z-10 focus-within:z-10",
        animated && "transition-[left] duration-[var(--motion-data)]",
      )}
      style={{ left: x - PIN_SIZE / 2, width: PIN_SIZE }}
    >
      <button
        type="button"
        aria-label={pin.title}
        onClick={() => onPin?.(pin.entryId)}
        className="flex size-4 items-center justify-center rounded-full border border-n-line bg-n-surface text-n-text-2 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-n-ink group-hover:border-n-ink group-hover:bg-n-ink group-hover:text-n-on-ink group-focus-within:border-n-ink group-focus-within:bg-n-ink group-focus-within:text-n-on-ink"
      >
        <PinIcon actor={pin.actor} />
      </button>
      <span aria-hidden className="h-5 w-px bg-n-line group-hover:bg-n-ink group-focus-within:bg-n-ink" />
      <div
        aria-hidden
        className={cn(
          "pointer-events-none absolute bottom-[calc(100%+4px)] hidden w-max max-w-[520px] items-center gap-2 rounded-n-control bg-n-ink px-2 py-1 group-hover:flex group-focus-within:flex",
          flip ? "right-[-4px]" : "left-[-4px]",
        )}
      >
        <span className="n-meta font-medium text-n-on-ink">{pin.title}</span>
        {pin.detail && <span className="n-label truncate font-normal text-n-text-3">{pin.detail}</span>}
        <ArrowDownRight size={12} className="shrink-0 text-n-text-3" />
      </div>
    </div>
  );
}

function OthersList({ options, band, column }: { options: ShareOption[]; band: ShareBand; column: ShareColumn }) {
  const total = columnTotal(column);
  return (
    <>
      {band.members.map((index) => (
        <span key={options[index].key} className="n-meta flex items-baseline justify-between gap-4">
          <span className="text-n-text-1">{options[index].name}</span>
          <span className="tabular-nums text-n-text-2">{percent(total ? (column.decisions[index] ?? 0) / total : 0)}</span>
        </span>
      ))}
    </>
  );
}

function EndLabel({
  band,
  share,
  options,
  column,
  frozen,
}: {
  band: ShareBand;
  share: number | null;
  options: ShareOption[];
  column?: ShareColumn;
  frozen: boolean;
}) {
  const leading = band.rank === 0;
  const body = (
    <>
      <LiveNumber
        mode={frozen ? "frozen" : "step"}
        value={share === null ? "—" : percent(share)}
        showFrom={false}
        className={cn("n-label font-normal", leading ? "font-semibold text-n-text-1" : "text-n-text-3")}
      />
      <span className={cn("n-meta truncate", leading ? "text-n-text-1" : "text-n-text-2")}>{band.name}</span>
    </>
  );

  return (
    <div className="flex min-h-[17px] min-w-0 items-center gap-1" style={{ flex: `${share ?? 1} 1 0` }}>
      {band.rank === 3 && column ? (
        <HoverCard
          align="right"
          trigger={
            <button
              type="button"
              className="flex min-w-0 items-center gap-1 rounded-n-chip focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-n-ink"
            >
              {body}
            </button>
          }
        >
          <OthersList options={options} band={band} column={column} />
        </HoverCard>
      ) : (
        body
      )}
    </div>
  );
}

/** share of decisions over the current cycle. qbrix picks the interval, so a new
    loop and a forty-day-old one are the same view: merging is the only motion */
export function ShareChart({
  since,
  until,
  options,
  columns,
  pins,
  onPin,
  range,
  onRangeChange,
  caption,
  frozen: paused,
  className,
}: {
  /** the range shown, in ms: the page clamps it to the cycle's start */
  since: number;
  until: number;
  options: ShareOption[];
  /** at this step or finer, oldest first, with no gaps */
  columns: ShareColumn[];
  pins?: SharePin[];
  onPin?: (entryId: string) => void;
  range: ShareRange;
  onRangeChange: (range: ShareRange) => void;
  /** already formatted: "cycle 2, 3 Oct to now" */
  caption?: string;
  /** a paused loop's figures. the chart also freezes while the server isn't answering */
  frozen?: boolean;
  className?: string;
}) {
  const unreachable = useFrozen();
  const frozen = paused || unreachable !== null;

  const plotRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const plot = plotRef.current;
    if (!plot) return;
    const measure = () => setWidth(plot.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(plot);
    return () => observer.disconnect();
  }, []);

  const step = pickInterval(since, until);
  const shown = useMemo(() => mergeColumns(columns, step).slice(-MAX_COLUMNS), [columns, step]);
  const bands = useMemo(() => rankBands(options, shown), [options, shown]);
  const rects = useMemo(() => columnRects(shown, bands, width, PLOT_HEIGHT, COLUMN_GAP), [shown, bands, width]);

  const [tween, setTween] = useState<{ from: ShareColumn[]; t: number } | null>(null);
  const previous = useRef({ step, range, shown });

  useLayoutEffect(() => {
    const last = previous.current;
    previous.current = { step, range, shown };
    if (range !== last.range || step <= last.step || step % last.step !== 0) return;

    const motion = getComputedStyle(document.documentElement).getPropertyValue("--motion-data").trim();
    const duration = parseFloat(motion) * (motion.endsWith("ms") ? 1 : 1000);
    if (!duration) return;

    let frame = 0;
    const started = performance.now();
    const advance = (now: number) => {
      const t = (now - started) / duration;
      if (t >= 1) {
        setTween(null);
        return;
      }
      setTween({ from: last.shown, t: easeOut(t) });
      frame = requestAnimationFrame(advance);
    };
    setTween({ from: last.shown, t: 0 });
    frame = requestAnimationFrame(advance);
    return () => {
      cancelAnimationFrame(frame);
      setTween(null);
    };
  }, [step, range, shown]);

  const drawn = useMemo(() => {
    if (!tween) return rects;
    const from = columnRects(tween.from, bands, width, PLOT_HEIGHT, COLUMN_GAP);
    return mergeTween(from, rects, step, tween.t);
  }, [tween, rects, bands, width, step]);

  const newest = useMemo(() => [...shown].reverse().find((column) => columnTotal(column) > 0), [shown]);
  const shares = newest ? bandShares(newest, bands) : null;
  const othersBand = bands.find((band) => band.rank === 3);

  const [hovered, setHovered] = useState<{ x: number; column: ShareColumn } | null>(null);

  const first = shown[0]?.at ?? since;
  const end = shown.length > 0 ? shown[shown.length - 1].at + step : until;
  const labels = useMemo(() => axisLabels(first, end), [first, end]);

  const placedPins = useMemo(() => {
    const perColumn = new Map<number, number>();
    return (pins ?? []).flatMap((pin) => {
      if (pin.at < since) return [];
      const column = Math.max(Math.floor(pin.at / step) * step, first);
      const rect = rects.find(({ at }) => at === column);
      if (!rect) return [];
      const fan = perColumn.get(column) ?? 0;
      perColumn.set(column, fan + 1);
      const x = rect.x + rect.width / 2 + fan * PIN_FAN;
      return [{ pin, x, flip: x > width / 2 }];
    });
  }, [pins, since, first, step, rects, width]);

  const summary = bands
    .map((band, at) => `${band.name} ${shares ? percent(shares[at]) : "no decisions yet"}`)
    .join(", ");

  return (
    <section className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-center gap-2">
        <h3 className="n-body font-medium text-n-text-1">Share of decisions</h3>
        {caption && <span className="n-body min-w-0 truncate text-n-text-3">{caption}</span>}
        <Segmented label="Range" value={range} options={RANGES} onChange={onRangeChange} className="ml-auto shrink-0" />
      </div>

      <div className="flex gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          {pins && pins.length > 0 && (
            <div className="relative" style={{ height: PIN_LANE_HEIGHT }}>
              {placedPins.map(({ pin, x, flip }) => (
                <Pin key={pin.entryId} pin={pin} x={x} flip={flip} animated={tween !== null} onPin={onPin} />
              ))}
            </div>
          )}

          <div ref={plotRef} className="relative" style={{ height: PLOT_HEIGHT }}>
            {width > 0 && (
              <svg role="img" aria-label={`Share of decisions: ${summary}`} width={width} height={PLOT_HEIGHT} className="block">
                {drawn.map((rect) => {
                  const column = shown.find(({ at }) => at === rect.at);
                  return rect.segments.map((segment) => (
                    <rect
                      key={`${rect.at}-${segment.rank}`}
                      x={rect.x}
                      y={segment.y}
                      width={Math.max(rect.width, 0)}
                      height={Math.max(segment.height, 0)}
                      className={(frozen ? FROZEN_TONE : TONE)[segment.rank]}
                      onPointerEnter={
                        segment.rank === 3 && column ? () => setHovered({ x: rect.x + rect.width / 2, column }) : undefined
                      }
                      onPointerLeave={segment.rank === 3 ? () => setHovered(null) : undefined}
                    />
                  ));
                })}
              </svg>
            )}
            {hovered && othersBand && (
              <div
                role="tooltip"
                className={cn(PANEL, "pointer-events-none absolute top-2 z-20 flex w-max max-w-[340px] flex-col gap-1.5 p-3 shadow-[0_8px_24px_#0000001f]")}
                style={
                  hovered.x > width / 2 ? { right: width - hovered.x + 6 } : { left: hovered.x + 6 }
                }
              >
                <OthersList options={options} band={othersBand} column={hovered.column} />
              </div>
            )}
          </div>

          <div className="relative h-4 pt-1">
            {width > 0 &&
              labels.map(({ at, label }, index) => {
                const last = index === labels.length - 1;
                return (
                  <span
                    key={at}
                    className="n-label absolute whitespace-nowrap font-normal tabular-nums text-n-text-3"
                    style={last ? { right: 0 } : { left: ((at - first) / (end - first)) * width }}
                  >
                    {label}
                  </span>
                );
              })}
          </div>
        </div>

        <div className="flex w-[132px] shrink-0 flex-col">
          {pins && pins.length > 0 && <div style={{ height: PIN_LANE_HEIGHT + 4 }} className="shrink-0" />}
          <div className="flex flex-col gap-px" style={{ height: PLOT_HEIGHT }}>
            {[...bands].reverse().map((band) => (
              <EndLabel
                key={band.key}
                band={band}
                share={shares ? shares[bands.indexOf(band)] : null}
                options={options}
                column={newest}
                frozen={frozen}
              />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
