"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";
import { DiffChip } from "@qbrix/ui/next/change";
import { ActorRef, LoopRef, MetricRef, OptionPill } from "@qbrix/ui/next/entity";
import { LiveNumber, LivePulse } from "@qbrix/ui/next/live-number";
import { frozenAt, useFrozen } from "@qbrix/ui/next/offline";
import type { Fact } from "@/lib/header/fact";
import { advance, counter, initialItem, itemMeta, pickItem, step, type ItemState } from "@/lib/header/item";
import { frozenEyebrow, type EyebrowToken, type Pulse, type StatusRow } from "@/lib/header/status";
import type { HeaderEvent, Token } from "@/lib/header/token";

const CLOCK_MS = 60_000;
const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-n-ink";

export function Header({
  name,
  row,
  eyebrow,
  pulse,
  events = [],
  facts = [],
  shortcuts = true,
  className,
}: {
  /** absent on the event log and Changes, which keep only the eyebrow */
  name?: string;
  /** absent on settings pages: a plain title, an eyebrow and facts */
  row?: Pick<StatusRow, "phrase" | "hint" | "pulse" | "name">;
  eyebrow: EyebrowToken[][];
  pulse?: Pulse;
  events?: HeaderEvent[];
  facts?: Fact[];
  /** j and k step this header's item. only one header on a page may have them */
  shortcuts?: boolean;
  className?: string;
}) {
  const title = row?.name ?? name;
  const hint = row?.hint;

  return (
    <header className={cn("flex flex-col gap-4 pb-2", className)}>
      <Eyebrow segments={eyebrow} pulse={pulse ?? row?.pulse ?? "live"} />
      {title && (
        <h1 className="text-[28px] font-normal leading-[34px] tracking-[-0.5px]">
          <span className="font-medium text-n-text-1">{title}</span>
          {row && <span className="text-n-text-2"> {row.phrase}</span>}
        </h1>
      )}
      {hint && <p className="max-w-[640px] text-[15px] leading-[1.4] text-n-text-2">{hint}</p>}
      {!hint && events.length > 0 && <Item events={events} shortcuts={shortcuts} />}
      {!hint && facts.length > 0 && <Facts facts={facts} />}
    </header>
  );
}

function Eyebrow({ segments, pulse }: { segments: EyebrowToken[][]; pulse: Pulse }) {
  const frozen = useFrozen();
  const shown = frozen ? frozenEyebrow(segments, frozenAt(frozen)) : segments;

  return (
    <p className="n-label flex h-3.5 min-w-0 items-center gap-2 font-normal text-n-text-3">
      <LivePulse tone={pulse} />
      <span className="truncate">
        {shown.map((segment, at) => (
          <span key={at}>
            {at > 0 && " · "}
            {segment.map((token, part) =>
              token.kind === "text" ? (
                <span key={part}>{token.text}</span>
              ) : (
                <LiveNumber key={part} mode="tick" value={token.value} showFrom={false} />
              ),
            )}
          </span>
        ))}
      </span>
    </p>
  );
}

function useClock() {
  const frozen = useFrozen();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (frozen) return;
    const timer = setInterval(() => setNow(Date.now()), CLOCK_MS);
    return () => clearInterval(timer);
  }, [frozen]);

  return now;
}

function isTyping(target: EventTarget | null) {
  return target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
}

function Item({ events, shortcuts }: { events: HeaderEvent[]; shortcuts: boolean }) {
  const now = useClock();
  const picked = useMemo(() => pickItem(events, now), [events, now]);
  const [state, setState] = useState<ItemState>(() => initialItem(picked));
  const [leaving, setLeaving] = useState<HeaderEvent | null>(null);
  const [animate, setAnimate] = useState(false);
  const [turn, setTurn] = useState(0);

  const shown = picked.set.find((event) => event.id === state.shownId) ?? picked.set[0];

  const move = useCallback(
    (next: ItemState) => {
      setLeaving(shown ?? null);
      setAnimate(true);
      setState(next);
    },
    [shown],
  );

  useEffect(() => {
    const at = Date.now();
    const result = advance(state, picked, at);
    if (result.state !== state) {
      if (result.entered) move(result.state);
      else setState(result.state);
    }
    if (result.dueAt === null) return;
    const timer = setTimeout(() => setTurn((count) => count + 1), result.dueAt - at);
    return () => clearTimeout(timer);
  }, [state, picked, move, turn]);

  const stepBy = useCallback(
    (by: 1 | -1) => {
      const next = step(state, picked, by);
      if (next !== state) move(next);
    },
    [state, picked, move],
  );

  const many = picked.set.length > 1;

  useEffect(() => {
    if (!shortcuts || !many) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      if (e.key === "j") stepBy(1);
      else if (e.key === "k") stepBy(-1);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [shortcuts, many, stepBy]);

  if (!shown) return null;

  const onArrow = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    stepBy(e.key === "ArrowDown" ? 1 : -1);
  };

  return (
    <div
      role="group"
      aria-label="Events"
      tabIndex={many ? 0 : undefined}
      onKeyDown={many ? onArrow : undefined}
      className={cn("flex min-h-[42px] gap-3 rounded-n-chip", FOCUS)}
    >
      <div className="grid min-w-0 flex-1" aria-live="polite">
        {/* the row holds its tallest event, so stepping never moves the page below it */}
        {many &&
          picked.set.map((event) => (
            <div key={`size-${event.id}`} aria-hidden className="invisible min-w-0 [grid-area:1/1]">
              <ItemBody event={event} now={now} />
            </div>
          ))}
        {leaving && leaving.id !== shown.id && (
          <div
            key={`leaving-${leaving.id}`}
            aria-hidden
            onAnimationEnd={() => setLeaving(null)}
            className="n-item-leave pointer-events-none [grid-area:1/1]"
          >
            <ItemBody event={leaving} now={now} />
          </div>
        )}
        <div key={shown.id} className={cn("min-w-0 [grid-area:1/1]", animate && "n-item-enter")}>
          <ItemBody event={shown} now={now} />
        </div>
      </div>
      <div className="flex h-6 shrink-0 items-center gap-1">
        <span className="n-meta mr-1 tabular-nums text-n-text-3">{counter(picked, shown.id)}</span>
        {many && (
          <>
            <StepButton label="Previous event" onClick={() => stepBy(-1)} icon={<ChevronUp size={14} />} />
            <StepButton label="Next event" onClick={() => stepBy(1)} icon={<ChevronDown size={14} />} />
          </>
        )}
      </div>
    </div>
  );
}

function StepButton({ label, onClick, icon }: { label: string; onClick: () => void; icon: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className={cn(
        "inline-flex size-6 items-center justify-center rounded-n-control border border-n-line text-n-text-2 transition-colors hover:bg-n-fill-1",
        FOCUS,
      )}
    >
      {icon}
    </button>
  );
}

function ItemBody({ event, now }: { event: HeaderEvent; now: number }) {
  return (
    <div className="flex min-w-0 gap-3">
      {event.alert && <span aria-hidden className="w-[3px] shrink-0 self-stretch rounded-[2px] bg-n-part-fg" />}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-[15px] leading-[21px]">
          {event.pieces.map((token, at) => (
            <Piece key={at} token={token} />
          ))}
        </p>
        {event.diff && event.diff.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {event.diff.map((entry) => (
              <DiffChip key={entry.field} {...entry} />
            ))}
          </div>
        )}
        <p className="flex flex-wrap items-center gap-x-1.5 text-[12px] leading-[17px] text-n-text-3">
          {event.alert && (
            <>
              <span className="font-medium text-n-part-fg">Needs a look</span>
              <span aria-hidden>·</span>
            </>
          )}
          <span>{itemMeta(event, now).join(" · ")}</span>
        </p>
        {event.reason && <p className="n-meta truncate text-n-text-2">“{event.reason}”</p>}
      </div>
    </div>
  );
}

function Piece({ token }: { token: Token }) {
  switch (token.kind) {
    case "text":
      return <span className="text-n-text-2">{token.text}</span>;
    case "actor":
      return <ActorRef actor={token.actor} className="align-middle leading-[18px]" />;
    case "loop":
      return <LoopRef name={token.name} href={token.href} />;
    case "metric":
      return <MetricRef name={token.name} href={token.href} />;
    case "option":
      return <OptionPill name={token.name} rank={token.rank} className="align-middle leading-[18px]" />;
  }
}

function Facts({ facts }: { facts: Fact[] }) {
  return (
    <dl className="flex gap-6 border-t border-n-line-2 pt-4">
      {facts.map((fact) => (
        <div key={fact.key} className="flex min-h-[50px] min-w-0 flex-1 flex-col gap-1">
          <dt className="truncate text-[11px] font-medium leading-[13px] text-n-text-3">{fact.label}</dt>
          <dd className="flex flex-col gap-1">
            <span className="truncate text-[15px] font-medium leading-4 text-n-text-1">{fact.value}</span>
            <span className="min-h-[13px] truncate text-[11px] leading-[13px] text-n-text-3">{fact.caption}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}
