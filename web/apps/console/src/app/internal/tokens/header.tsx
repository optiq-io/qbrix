"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@qbrix/ui/next/button";
import { AskYourAgent } from "@qbrix/ui/next/empty";
import { FrozenProvider } from "@qbrix/ui/next/offline";
import { SkeletonHeader } from "@qbrix/ui/next/skeleton";
import { Header } from "@/components/next/header/header";
import { facts } from "@/lib/header/fact";
import { fixture, FIXTURES, leaderChanged, paused, type HeaderFixture } from "@/lib/header/fixture";
import { eyebrow, prompts, statusRow } from "@/lib/header/status";
import type { HeaderEvent } from "@/lib/header/token";

const STORM_GAPS_MS = [0, 2000, 4000, 6000, 8000];

function FixtureHeader({ entry, now }: { entry: HeaderFixture; now: number }) {
  const row = statusRow(entry.subject);
  return (
    <Header
      name={entry.name}
      row={row}
      eyebrow={eyebrow(row, entry.counters)}
      events={entry.events(now)}
      facts={facts(row, entry.values)}
      shortcuts={false}
    />
  );
}

function Labelled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3">
      <span className="n-meta text-n-text-3">{label}</span>
      {children}
    </div>
  );
}

function Storm({ now }: { now: number }) {
  const row = statusRow({ kind: "loop", status: "live" });
  const live = fixture("live");
  const [events, setEvents] = useState<HeaderEvent[]>(() => live.events(now));
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const count = useRef(0);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const arrive = (event: HeaderEvent) => setEvents((current) => [...current, event]);
  const fireFive = () => {
    timers.current.push(
      ...STORM_GAPS_MS.map((gap) =>
        setTimeout(() => {
          count.current += 1;
          arrive(leaderChanged(`storm-${count.current}`, Date.now()));
        }, gap),
      ),
    );
  };
  const alert = () => {
    count.current += 1;
    arrive(paused(`alert-${count.current}`, Date.now()));
  };
  const resolve = () => setEvents((current) => current.map((event) => ({ ...event, alert: false })));

  return (
    <div className="flex flex-col gap-3">
      <div data-header-storm>
        <Header name={live.name} row={row} eyebrow={eyebrow(row, live.counters)} events={events} facts={facts(row, live.values)} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" onClick={fireFive}>
          Five events in 8 s
        </Button>
        <Button variant="secondary" size="sm" onClick={alert}>
          An alert
        </Button>
        <Button variant="secondary" size="sm" onClick={resolve}>
          Resolve alerts
        </Button>
        <span className="n-meta text-n-text-3">j and k step this one; ↑ and ↓ with focus on its item</span>
      </div>
    </div>
  );
}

export function HeaderSheet() {
  const [now, setNow] = useState<number | null>(null);
  const [frozen, setFrozen] = useState<Date | null>(null);
  const live = fixture("live");
  const liveRow = statusRow(live.subject);

  useEffect(() => setNow(Date.now()), []);

  if (now === null) return null;

  return (
    <div className="flex flex-col gap-10">
      <Labelled label="Live arrivals: at most one entrance every 10 s, and an alert is never displaced">
        <Storm now={now} />
      </Labelled>

      <Labelled label="Server not answering: the eyebrow says when, and the pulse goes hollow">
        <div className="flex flex-col gap-3">
          <FrozenProvider since={frozen}>
            <FixtureHeader entry={live} now={now} />
          </FrozenProvider>
          <div>
            <Button variant="secondary" size="sm" onClick={() => setFrozen((at) => (at ? null : new Date()))}>
              {frozen ? "Answer again" : "Stop answering"}
            </Button>
          </div>
        </div>
      </Labelled>

      <Labelled label="Against its skeleton, which reserves the same height">
        <div className="grid gap-6 md:grid-cols-2">
          <div data-header-measure="real">
            <FixtureHeader entry={live} now={now} />
          </div>
          <div data-header-measure="skeleton">
            <SkeletonHeader />
          </div>
        </div>
      </Labelled>

      <Labelled label="Prompts, fixed per status: the page puts them at the rail's foot">
        <AskYourAgent className="max-w-[300px]" label="Ask your agent · about what's happening" prompts={prompts(liveRow, live.name ?? "")} />
      </Labelled>

      {FIXTURES.map((entry) => (
        <Labelled key={entry.key} label={entry.key}>
          <FixtureHeader entry={entry} now={now} />
        </Labelled>
      ))}

      <Labelled label="A settings page: a plain title, an eyebrow and facts">
        <Header
          name="Your connections"
          eyebrow={[[{ kind: "counter", value: "3" }, { kind: "text", text: " connections" }], [{ kind: "text", text: "2 used today" }]]}
          facts={[
            { key: "changes", label: "Changes", value: "53", caption: "this week" },
            { key: "asked", label: "Asked first", value: "1", caption: "this week" },
            { key: "waiting", label: "Waiting on you", value: "1", caption: "change" },
          ]}
          shortcuts={false}
        />
      </Labelled>

      <Labelled label="The event log and Changes: only the eyebrow">
        <Header eyebrow={[[{ kind: "counter", value: "1,240" }, { kind: "text", text: " decisions a second" }]]} shortcuts={false} />
      </Labelled>
    </div>
  );
}
