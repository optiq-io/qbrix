"use client";

import { useEffect, useMemo, useState } from "react";
import { Change, HISTORY_LINE_INSET, type ChangeData } from "@qbrix/ui/next/change";
import type { Actor } from "@qbrix/ui/next/entity";
import { FilterToggle } from "@qbrix/ui/next/list";
import { StateBadge } from "@qbrix/ui/next/state";
import { StreamLanes, StreamRows, type OutcomeState, type StreamLane, type StreamRow } from "@qbrix/ui/next/stream";
import { RailLine, TimeRail, type RailEntry } from "@qbrix/ui/next/time-rail";

type FixtureCycle = {
  id: string;
  title: string;
  span: string;
  live: boolean;
  shares: [string, number][];
  story: { key: string; at: string; text: string }[];
};

const CYCLES: FixtureCycle[] = [
  {
    id: "c3",
    title: "Cycle 3",
    span: "since 9 Oct · 6 days",
    live: true,
    shares: [["Pay in one tap", 58], ["Fewer returns", 27], ["Ships today", 15]],
    story: [
      { key: "c3-audience", at: "13 Oct", text: "Ada narrowed the audience" },
      { key: "c3-engine", at: "11 Oct", text: "Engine 1.2 → 1.3 with the qbrix upgrade · learned state unchanged" },
      { key: "c3-began", at: "9 Oct", text: "Started by Mustafa via Claude Code: Ships today replaced Lowest price" },
    ],
  },
  {
    id: "c2",
    title: "Cycle 2",
    span: "3 – 9 Oct · 6 days",
    live: false,
    shares: [["Fewer returns", 46], ["Pay in one tap", 41], ["Lowest price", 13]],
    story: [
      { key: "c2-sealed", at: "9 Oct", text: "Sealed when cycle 3 started: Lowest price had 6% for two days" },
      { key: "c2-began", at: "3 Oct", text: "Started by Ada" },
    ],
  },
  {
    id: "c1",
    title: "Cycle 1",
    span: "1 – 3 Oct · 3 days",
    live: false,
    shares: [["Fewer returns", 50], ["Pay in one tap", 44], ["Lowest price", 6]],
    story: [
      { key: "c1-sealed", at: "3 Oct", text: "Sealed when cycle 2 started" },
      { key: "c1-launched", at: "1 Oct", text: "Launched by Mustafa" },
    ],
  },
];

const CYCLE_ENTRIES: RailEntry[] = [
  { key: "now", kind: "now", at: "Now", state: "live" },
  ...CYCLES.flatMap((cycle, index): RailEntry[] => {
    const number = CYCLES.length - index;
    const state = cycle.live ? "live" : "sealed";
    return [
      { key: cycle.id, kind: "cycle", at: cycle.title, cycle: number, state },
      ...cycle.story.map(({ key, at }, line): RailEntry => {
        const oldest = line === cycle.story.length - 1;
        const kind = !oldest ? "tick" : number === 1 ? "origin" : cycle.live ? "began" : "tick";
        return { key, kind, at, cycle: number, state };
      }),
    ];
  }),
];

function CycleCard({ cycle, grown }: { cycle: FixtureCycle; grown: boolean }) {
  return (
    <div className={`rounded-n-panel border bg-n-surface p-4 ${cycle.live ? "border-n-ink" : "border-n-line"}`}>
      <RailLine entry={cycle.id} className="n-support flex items-center gap-2">
        <span className="font-semibold">{cycle.title}</span>
        {cycle.live ? <StateBadge state="ok">Live</StateBadge> : <StateBadge>Sealed</StateBadge>}
        <span className="n-meta text-n-text-2">{cycle.span}</span>
      </RailLine>
      <div className="flex flex-col gap-2 py-3">
        {cycle.shares.map(([option, share], rank) => (
          <div key={option} className="n-meta flex items-center gap-3">
            <span className="w-28 truncate">{option}</span>
            <span className="h-1.5 flex-1 bg-n-viz-track">
              <span
                className={`block h-full ${["bg-n-ink", "bg-n-viz-2", "bg-n-viz-3"][rank]}`}
                style={{ width: `${share}%` }}
              />
            </span>
            <span className="w-8 text-right tabular-nums">{share}%</span>
          </div>
        ))}
        {grown && (
          <p className="n-meta text-n-text-2">
            Added height, to check that the ticks below follow their lines at any card height.
            <br />
            A second line of it.
            <br />
            And a third.
          </p>
        )}
      </div>
      <div className="flex flex-col gap-1 border-t border-n-line-2 pt-3">
        {cycle.story.map(({ key, text }) => (
          <RailLine key={key} entry={key} className="n-meta text-n-text-2">
            {text}
          </RailLine>
        ))}
      </div>
    </div>
  );
}

function CyclesFixture() {
  const [grown, setGrown] = useState(false);
  return (
    <div className="flex flex-col gap-4">
      <FilterToggle label="Taller cards" pressed={grown} onChange={setGrown} className="self-start" />
      <TimeRail entries={CYCLE_ENTRIES} className="max-w-[780px]">
        <RailLine entry="now" className="n-meta pb-4 text-n-text-3">
          Day 6 of cycle 3 · learned 40 seconds ago
        </RailLine>
        <div className="flex flex-col gap-8">
          {CYCLES.map((cycle) => (
            <CycleCard key={cycle.id} cycle={cycle} grown={grown} />
          ))}
        </div>
      </TimeRail>
    </div>
  );
}

const ADA: Actor = { kind: "member", name: "Ada" };
const MUSTAFA: Actor = { kind: "member", name: "Mustafa" };
const CLAUDE: Actor = { kind: "connection", name: "Claude Code", onBehalfOf: "Mustafa" };
const QBRIX: Actor = { kind: "qbrix" };
const LOOP = { kind: "loop", name: "Checkout headline" } as const;

const HISTORY: { entry: RailEntry; change: ChangeData }[] = [
  {
    entry: { key: "h-declined", kind: "declined", at: "12 Oct", cycle: 2, state: "live" },
    change: {
      actor: CLAUDE,
      verb: "proposed retiring an option on",
      target: LOOP,
      reason: "Ships today has lost share for six days.",
      context: "declined by Ada",
      time: "16:40",
    },
  },
  {
    entry: { key: "h-resume", kind: "tick", at: "6 Oct", cycle: 2, state: "live" },
    change: { actor: MUSTAFA, verb: "resumed", target: LOOP, time: "02:43" },
  },
  {
    entry: { key: "h-pause", kind: "pause", at: "6 Oct", cycle: 2, state: "live" },
    change: {
      actor: QBRIX,
      verb: "paused",
      target: LOOP,
      diff: [{ field: "state", before: "live", after: "paused" }],
      context: "safety pause",
      time: "02:10",
    },
  },
  {
    entry: { key: "h-began", kind: "began", at: "3 Oct", cycle: 2, state: "live" },
    change: {
      actor: CLAUDE,
      verb: "started cycle 2 of",
      target: LOOP,
      diff: [{ field: "options", before: "Lowest price", after: "Ships today" }],
      reason: "Lowest price had 6% of traffic for two days.",
      time: "10:00",
    },
  },
  {
    entry: { key: "h-sealed", kind: "tick", at: "3 Oct", cycle: 1, state: "sealed" },
    change: { actor: QBRIX, verb: "sealed cycle 1 of", target: LOOP, time: "10:00" },
  },
  {
    entry: { key: "h-launch", kind: "tick", at: "1 Oct", cycle: 1, state: "sealed" },
    change: { actor: MUSTAFA, verb: "launched", target: LOOP, time: "11:00" },
  },
  {
    entry: { key: "h-drafted", kind: "origin", at: "1 Oct", cycle: 1, state: "sealed" },
    change: { actor: ADA, verb: "drafted", target: LOOP, time: "09:30" },
  },
];

const HISTORY_ENTRIES: RailEntry[] = [
  { key: "now", kind: "now", at: "Now", state: "live" },
  { key: "head-2", kind: "cycle", cycle: 2, state: "live" },
  ...HISTORY.slice(0, 4).map(({ entry }) => entry),
  { key: "head-1", kind: "cycle", cycle: 1, state: "sealed" },
  ...HISTORY.slice(4).map(({ entry }) => entry),
];

function CycleHead({ entry, title, span }: { entry: string; title: string; span: string }) {
  return (
    <RailLine entry={entry} className="n-support flex items-center gap-2 px-3 py-2">
      <span className="font-semibold">{title}</span>
      <span className="n-meta text-n-text-2">{span}</span>
    </RailLine>
  );
}

function HistoryFixture() {
  const rows = (from: number, to: number) =>
    HISTORY.slice(from, to).map(({ entry, change }) => (
      <RailLine key={entry.key} entry={entry.key} inset={HISTORY_LINE_INSET} className="n-body">
        <Change layout="history" change={change} />
      </RailLine>
    ));

  return (
    <TimeRail entries={HISTORY_ENTRIES} className="max-w-[780px]">
      <RailLine entry="now" className="n-meta pb-2 pl-3 text-n-text-3">
        Day 12 of cycle 2 · learned 40 seconds ago
      </RailLine>
      <CycleHead entry="head-2" title="Cycle 2" span="since 3 Oct" />
      {rows(0, 4)}
      <CycleHead entry="head-1" title="Cycle 1" span="1 – 3 Oct · 3 days" />
      {rows(4, HISTORY.length)}
    </TimeRail>
  );
}

const DRAFT_ENTRIES: RailEntry[] = [
  { key: "now", kind: "now", at: "Now", state: "sealed" },
  { key: "drafted", kind: "origin", at: "27 Oct", state: "sealed" },
];

function DraftFixture() {
  return (
    <TimeRail entries={DRAFT_ENTRIES} className="max-w-[780px]">
      <RailLine entry="now" className="n-meta pb-4 text-n-text-3">
        A draft, not deciding yet
      </RailLine>
      <RailLine entry="drafted" className="n-meta text-n-text-2">
        Created by Ada
      </RailLine>
    </TimeRail>
  );
}

function wave(seed: number, floor: number, gapAt?: number): number[] {
  return Array.from({ length: 90 }, (_, i) => {
    if (gapAt !== undefined && i >= gapAt && i < gapAt + 8) return 0;
    return floor + ((i * seed) % 7) + ((i * (seed + 3)) % 5);
  });
}

const LANES: StreamLane[] = [
  { key: "checkout-headline", name: "Checkout headline", state: "ok", pulse: wave(3, 8), rate: "38 / s", outcomes: "outcomes 99.1% learned" },
  { key: "pricing-cta", name: "Pricing page CTA", state: "ok", pulse: wave(5, 8), rate: "22 / s", outcomes: "outcomes 98.4% learned" },
  { key: "onboarding", name: "Onboarding steps", state: "ok", pulse: wave(4, 6, 60), rate: "11 / s", outcomes: "outcomes 97.9% learned" },
  {
    key: "search-ranking",
    name: "Search ranking",
    state: "part",
    pulse: wave(2, 2),
    rate: "1,169 / s · default",
    outcomes: "paused · answering with Relevance",
    paused: true,
  },
];

const OPTIONS = ["Pay in one tap", "Fewer returns", "Ships today"];
const UNITS = ["mobile NL returning", "mobile BE new", "mobile DE new", "desktop FR returning"];
const OUTCOMES: { state: OutcomeState; note: string }[] = [
  { state: "waiting", note: "seals in 24 h" },
  { state: "learned", note: "= 1 · 4.2 s" },
  { state: "waiting", note: "seals in 24 h" },
  { state: "learned", note: "= 1 · 11.0 s" },
  { state: "sealed", note: "no outcome · counts 0" },
  { state: "late", note: "= 1 · after 25 h" },
];

function fixtureRow(i: number, lane: string): StreamRow {
  if (i % 97 === 96) {
    return { kind: "marker", key: `${lane}-m${i}`, label: `#${i} merged · Track checkout on the new payment sheet` };
  }
  if (i % 211 === 210) {
    return {
      kind: "decision",
      key: `${lane}-${i}`,
      decided: clock(i),
      unit: `u_${(i * 2654435761 % 65536).toString(16)} · no open decision`,
      outcome: { state: "unattributed", note: "recorded only" },
    };
  }
  return {
    kind: "decision",
    key: `${lane}-${i}`,
    decided: clock(i),
    option: OPTIONS[i % 3 === 0 ? 1 : i % 5 === 0 ? 2 : 0],
    unit: `u_${(i * 2654435761 % 65536).toString(16)} · ${UNITS[i % UNITS.length]}`,
    why: i % 3 === 0 ? "exploring" : "best so far",
    outcome: OUTCOMES[i % OUTCOMES.length],
  };
}

function clock(i: number) {
  const seconds = 100000 - i;
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(Math.floor(seconds / 3600) % 24)}:${pad(Math.floor(seconds / 60) % 60)}:${pad(seconds % 60)}.${String(i % 1000).padStart(3, "0")}`;
}

const ROW_COUNT = 5000;

function StreamFixture() {
  const [lane, setLane] = useState<string | undefined>();
  const [picked, setPicked] = useState<string | undefined>();
  const [live, setLive] = useState(false);
  const [added, setAdded] = useState(0);

  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => setAdded((count) => count + 1), 500);
    return () => clearInterval(timer);
  }, [live]);

  const prefix = lane ?? "all";
  const base = useMemo(() => Array.from({ length: ROW_COUNT }, (_, i) => fixtureRow(i, prefix)), [prefix]);
  const rows = useMemo(() => {
    const fresh = Array.from({ length: added }, (_, i) => {
      const row = fixtureRow(added - i, `${prefix}-new`);
      return row.kind === "decision" ? { ...row, decided: `new ${added - i}` } : row;
    });
    return [...fresh, ...base];
  }, [added, base, prefix]);

  return (
    <div className="flex flex-col gap-4">
      <StreamLanes
        lanes={LANES}
        selected={lane}
        onSelect={(next) => setLane((current) => (current === next.key ? undefined : next.key))}
      />
      <FilterToggle label="New rows arriving" pressed={live} onChange={setLive} className="self-start" />
      <StreamRows
        rows={rows}
        selected={picked}
        onSelect={(row) => setPicked(row.key)}
        className="h-[420px]"
      />
    </div>
  );
}

export function RailAndStream() {
  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-2">
        <span className="n-meta text-n-text-3">TimeRail: cycles, one live and two sealed</span>
        <CyclesFixture />
      </div>
      <div className="flex flex-col gap-2">
        <span className="n-meta text-n-text-3">TimeRail: history, with a declined proposal, a pause and the origin</span>
        <HistoryFixture />
      </div>
      <div className="flex flex-col gap-2">
        <span className="n-meta text-n-text-3">TimeRail: a draft, nothing live</span>
        <DraftFixture />
      </div>
      <div className="flex flex-col gap-2">
        <span className="n-meta text-n-text-3">StreamLanes and StreamRows: 5,000 rows</span>
        <StreamFixture />
      </div>
    </div>
  );
}
