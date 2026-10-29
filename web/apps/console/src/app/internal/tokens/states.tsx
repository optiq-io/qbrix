"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { BellOff, Info, Plus } from "lucide-react";
import { PageReveal } from "@qbrix/ui/components/page-reveal";
import { Button } from "@qbrix/ui/next/button";
import { AskYourAgent, Code, Empty, Note } from "@qbrix/ui/next/empty";
import { LargerScreen } from "@qbrix/ui/next/larger-screen";
import { FrozenProvider, Offline } from "@qbrix/ui/next/offline";
import { CouldntLoad, NotFound } from "@qbrix/ui/next/page-error";
import { SkeletonBlock, SkeletonHeader, SkeletonList, SkeletonRail, SkeletonText } from "@qbrix/ui/next/skeleton";

const HOME = { href: "/internal/tokens", label: "Go to loops" };
const FROZEN_AT = new Date(2026, 9, 29, 14, 2);

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="n-meta text-n-text-3">{label}</span>
      {children}
    </div>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  return <div className="flex overflow-hidden rounded-n-panel border border-n-line bg-n-surface">{children}</div>;
}

export function States() {
  return (
    <div className="flex flex-col gap-8">
      <Row label="Empty · home, no loops">
        <Empty
          agent={{
            title: "Let your agent draft it",
            line: "It finds the place in your code, drafts the loop and asks you before it launches.",
            prompt: "Start a loop for the checkout headline",
            connect: { command: "claude mcp add qbrix https://qbrix.acme.dev/mcp", href: "#" },
          }}
          hand={{
            title: "Make a loop yourself",
            line: "Name it, list its options and choose the metric it learns from. It starts as a draft, so nothing changes for your users until you launch it.",
            children: (
              <Button className="self-start">
                <Plus size={14} />
                New loop
              </Button>
            ),
          }}
        />
      </Row>

      <Row label="AskYourAgent, Code and Note">
        <div className="grid gap-6 md:grid-cols-2">
          <AskYourAgent prompts={["Where in our app would a loop help?", "Wire qbrix into the checkout page"]} />
          <div className="flex flex-col gap-3">
            <Code>track(&quot;checkout_completed&quot;, 1)</Code>
            <Note icon={BellOff} title="Alerts only reach you in the console.">
              Add the workspace webhook in Settings to get them in Slack.
            </Note>
            <Note icon={Info}>
              A draft&apos;s calls get its fallback and show on its own page, not here. Only a live loop makes decisions.
            </Note>
          </div>
        </div>
      </Row>

      <Row label="Skeleton and PageReveal · the height must not change on reveal">
        <RevealFixture />
      </Row>

      <Row label="Skeleton · list and rail">
        <div className="flex flex-col gap-8">
          <div>
            <SkeletonList
              columns={[{ lines: [140, 233] }, { width: 150, lines: [117] }, { width: 140, lines: [93, 71] }, { width: 110, lines: [40] }]}
              rows={3}
            />
          </div>
          <div className="w-[252px]">
            <SkeletonRail groups={[5, 3]} />
          </div>
        </div>
      </Row>

      <Row label="NotFound · a loop key, with the closest key">
        <Frame>
          <NotFound
            path="/loops/checkout-headlin"
            noun="loop"
            workspace="acme"
            email="mustafa@acme.dev"
            closest={{ name: "Checkout headline", key: "checkout-headline", href: "#" }}
            home={HOME}
            onSwitchAccount={() => undefined}
          />
        </Frame>
      </Row>

      <Row label="CouldntLoad">
        <Frame>
          <CouldntLoad requestId="req_7f3a91c2e0" onRetry={() => undefined} home={HOME} />
        </Frame>
      </Row>

      <Row label="Offline · frozen as of 14:02">
        <Frame>
          <div className="flex-1">
            <FrozenProvider since={FROZEN_AT}>
              <Offline onRetry={() => undefined} />
            </FrozenProvider>
          </div>
        </Frame>
      </Row>

      <Row label="LargerScreen · on a phone">
        <div className="w-[358px]">
          <LargerScreen title="Metrics open on a larger screen" />
        </div>
      </Row>
    </div>
  );
}

function RevealFixture() {
  const [ready, setReady] = useState(false);
  const [round, setRound] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const [heights, setHeights] = useState<number[]>([]);

  useLayoutEffect(() => {
    if (ref.current) setHeights((h) => [...h, ref.current!.offsetHeight]);
  }, [ready, round]);

  useEffect(() => {
    const timer = window.setTimeout(() => setReady(true), 1200);
    return () => window.clearTimeout(timer);
  }, [round]);

  function load() {
    setReady(false);
    setHeights([]);
    setRound((r) => r + 1);
  }

  const [skeleton, loaded] = heights;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Button variant="secondary" size="sm" onClick={load}>
          Load again
        </Button>
        <span className="n-meta tabular-nums text-n-text-2">
          {skeleton !== undefined && loaded !== undefined
            ? `skeleton ${skeleton}px · revealed ${loaded}px${skeleton === loaded ? " · no shift" : " · shifted"}`
            : "loading"}
        </span>
      </div>
      <div ref={ref}>
        <PageReveal key={round} ready={ready} skeleton={<FixtureSkeleton />}>
          <FixturePage />
        </PageReveal>
      </div>
    </div>
  );
}

function FixtureSkeleton() {
  return (
    <div className="flex flex-col gap-9">
      <SkeletonHeader />
      <div className="flex flex-col gap-2">
        <SkeletonText width={78} />
        <SkeletonBlock height={218} />
      </div>
    </div>
  );
}

const FACTS = [
  ["Ahead", "Pay in one tap", "option"],
  ["Share", "58%", "of decisions, last 24 h"],
  ["Lift", "+6.2%", "vs an even split"],
  ["Waiting", "214", "decisions to seal"],
] as const;

function FixturePage() {
  return (
    <div className="flex flex-col gap-9">
      <div className="flex flex-col gap-4 pb-2">
        <p className="n-label flex h-3.5 items-center font-normal text-n-text-3">38 decisions a second · learned 40 seconds ago</p>
        <h3 className="n-lead flex h-[34px] items-center">
          <span className="font-medium">Checkout headline</span>&nbsp;is live and learning.
        </h3>
        <div className="flex h-[42px] flex-col justify-center">
          <p className="n-body text-n-text-1">Pay in one tap took the lead from Ships today.</p>
          <p className="n-meta text-n-text-3">qbrix · 2 days ago</p>
        </div>
        <div className="flex gap-6 border-t border-n-line-2 pt-4">
          {FACTS.map(([label, value, caption]) => (
            <div key={label} className="flex h-[50px] flex-1 flex-col justify-center">
              <span className="n-label text-n-text-3">{label}</span>
              <span className="n-body font-medium tabular-nums">{value}</span>
              <span className="n-label font-normal text-n-text-3">{caption}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <p className="n-body font-medium">How it learned</p>
        <div className="h-[218px] rounded-n-control bg-n-viz-track" />
      </div>
    </div>
  );
}
