"use client";

import { useEffect, useMemo, useState } from "react";
import { FilterToggle } from "@qbrix/ui/next/list";
import { LiveNumber, LivePulse } from "@qbrix/ui/next/live-number";
import { FrozenProvider } from "@qbrix/ui/next/offline";
import {
  ShareChart,
  type ShareColumn,
  type ShareOption,
  type SharePin,
  type ShareRange,
} from "@qbrix/ui/next/share-chart";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const CYCLE_START = Date.UTC(2026, 9, 3, 14);
const CYCLE_MINUTES = 40 * 24 * 60;
const WINDOW: Record<ShareRange, number> = { "24h": DAY, "7d": 7 * DAY, cycle: Infinity };

const THREE: ShareOption[] = [
  { key: "one-tap", name: "Pay in one tap" },
  { key: "returns", name: "Fewer returns" },
  { key: "today", name: "Ships today" },
];

const FIVE: ShareOption[] = [
  ...THREE,
  { key: "price", name: "Lowest price" },
  { key: "reviews", name: "Top reviewed" },
];

function minuteColumns(options: ShareOption[]): ShareColumn[] {
  return Array.from({ length: CYCLE_MINUTES }, (_, minute) => {
    const age = Math.min(1, minute / (12 * 24 * 60));
    const wobble = Math.sin(minute / 97) * 0.02;
    const shares = [0.41 + 0.17 * age + wobble, 0.33 - 0.04 * age - wobble, 0.26 - 0.13 * age];
    const rest = options.length > 3 ? [0.05, 0.03] : [];
    return {
      at: CYCLE_START + minute * MINUTE,
      decisions: [...shares, ...rest].map((share) => Math.round(share * 400)),
    };
  });
}

const PINS: SharePin[] = [
  {
    at: CYCLE_START + 2 * MINUTE,
    entryId: "started",
    actor: { kind: "connection", name: "Claude Code", onBehalfOf: "Mustafa" },
    title: "Mustafa via Claude Code started cycle 2",
    detail: "3 Oct · Ships today replaced Lowest price",
  },
  {
    at: CYCLE_START + 25 * HOUR,
    entryId: "audience",
    actor: { kind: "member", name: "Ada" },
    title: "Ada narrowed the audience",
    detail: "all → mobile · 4 Oct · share 41% → 58%",
  },
  {
    at: CYCLE_START + 25 * HOUR + 3 * MINUTE,
    entryId: "merged",
    actor: { kind: "github", name: "GitHub" },
    title: "#491 merged",
    detail: "4 Oct · Track checkout on the new payment sheet",
  },
  {
    at: CYCLE_START + 5 * DAY,
    entryId: "engine",
    actor: { kind: "qbrix" },
    title: "Engine 1.2 → 1.3",
    detail: "8 Oct · learned state unchanged",
  },
];

const AGE_STOPS = [1, 20, 60, 540, 1440, 4320, 17280, 57600];

function formatAge(minutes: number) {
  if (minutes < 120) return `${Math.round(minutes)} minutes`;
  if (minutes < 2880) return `${Math.round(minutes / 60)} hours`;
  return `${Math.round(minutes / 1440)} days`;
}

function GrowingChart({ options, title }: { options: ShareOption[]; title: string }) {
  const raw = useMemo(() => minuteColumns(options), [options]);
  const [position, setPosition] = useState(Math.log(17280) / Math.log(57600));
  const [playing, setPlaying] = useState(false);
  const [range, setRange] = useState<ShareRange>("cycle");
  const [opened, setOpened] = useState<string>();

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      setPosition((current) => (current >= 1 ? 0 : Math.min(1, current + 0.004)));
    }, 50);
    return () => clearInterval(timer);
  }, [playing]);

  const age = Math.max(1, Math.round(57600 ** position));
  const until = CYCLE_START + age * MINUTE;
  const since = Math.max(CYCLE_START, until - WINDOW[range]);
  const columns = useMemo(
    () => raw.slice((since - CYCLE_START) / MINUTE, (until - CYCLE_START) / MINUTE),
    [raw, since, until],
  );

  return (
    <div className="flex max-w-[908px] flex-col gap-3">
      <div className="n-meta flex items-center gap-3 text-n-text-3">
        <span>{title}</span>
        <input
          type="range"
          aria-label="How old the cycle is"
          min={0}
          max={1}
          step={0.001}
          value={position}
          onChange={(e) => setPosition(Number(e.target.value))}
          className="min-w-0 flex-1"
        />
        <span className="w-20 tabular-nums text-n-text-1">{formatAge(age)}</span>
        <FilterToggle label="Grow" pressed={playing} onChange={setPlaying} />
        {AGE_STOPS.slice(1).map((stop) => (
          <button
            key={stop}
            type="button"
            className="tabular-nums hover:text-n-text-1"
            onClick={() => setPosition(Math.log(stop) / Math.log(57600))}
          >
            {formatAge(stop)}
          </button>
        ))}
      </div>
      <ShareChart
        since={since}
        until={until}
        options={options}
        columns={columns}
        pins={PINS.filter((pin) => pin.at < until)}
        onPin={setOpened}
        range={range}
        onRangeChange={setRange}
        caption="cycle 2, 3 Oct to now"
      />
      <span className="n-meta text-n-text-3">Opened from a pin: {opened ?? "nothing yet"}</span>
    </div>
  );
}

function FrozenChart() {
  const raw = useMemo(() => minuteColumns(THREE), []);
  const until = CYCLE_START + 12 * DAY;
  const [range, setRange] = useState<ShareRange>("cycle");
  return (
    <ShareChart
      since={CYCLE_START}
      until={until}
      options={THREE}
      columns={raw.slice(0, (until - CYCLE_START) / MINUTE)}
      range={range}
      onRangeChange={setRange}
      frozen
      className="max-w-[908px]"
    />
  );
}

function Numbers() {
  const [share, setShare] = useState(58);
  const [lift, setLift] = useState(0.8);
  const [rate, setRate] = useState(38);
  const paused = useMemo(() => new Date(2026, 9, 15, 14, 2), []);

  useEffect(() => {
    const timer = setInterval(() => setRate(36 + Math.floor(Math.random() * 5)), 1000);
    return () => clearInterval(timer);
  }, []);

  const row = "n-body flex min-h-7 items-center gap-3";
  const name = "n-meta w-16 text-n-text-3";

  return (
    <div className="flex flex-col gap-1">
      <div className={row}>
        <span className={name}>tick</span>
        <LivePulse />
        <LiveNumber mode="tick" value={String(rate)} /> <span className="text-n-text-2">decisions a second</span>
      </div>
      <div className={row}>
        <span className={name}>step</span>
        <LiveNumber mode="step" value={`${share}%`} />
        <button type="button" className="n-meta text-n-text-3 hover:text-n-text-1" onClick={() => setShare((s) => s + 1)}>
          Learn
        </button>
      </div>
      <div className={row}>
        <span className={name}>early</span>
        <LiveNumber mode="early" value={`+${lift.toFixed(1)}%`} />
        <button
          type="button"
          className="n-meta text-n-text-3 hover:text-n-text-1"
          onClick={() => setLift((value) => value + 0.3)}
        >
          Learn
        </button>
      </div>
      <div className={row}>
        <span className={name}>frozen</span>
        <LivePulse tone="paused" />
        <LiveNumber mode="frozen" value="44%" since={paused} />
      </div>
    </div>
  );
}

export function ShareAndNumbers() {
  const [offline, setOffline] = useState(false);
  const since = useMemo(() => (offline ? new Date() : null), [offline]);

  return (
    <div className="flex flex-col gap-8">
      <GrowingChart options={THREE} title="Three options" />
      <GrowingChart options={FIVE} title="Five options" />
      <div className="flex flex-col gap-2">
        <span className="n-meta text-n-text-3">A paused loop&apos;s chart</span>
        <FrozenChart />
      </div>
      <div className="flex flex-col gap-3">
        <FilterToggle label="Server not answering" pressed={offline} onChange={setOffline} className="self-start" />
        <FrozenProvider since={since}>
          <Numbers />
        </FrozenProvider>
      </div>
    </div>
  );
}
