"use client";

import { useState } from "react";
import { Box, Eye, Pause, Tag, Undo2 } from "lucide-react";
import { Button } from "@qbrix/ui/next/button";
import { Change, DiffChip, type ChangeActions, type ChangeData } from "@qbrix/ui/next/change";
import { AskYourAgent, Note } from "@qbrix/ui/next/empty";
import { ActorRef, LoopRef, MetricRef, OptionPill, type Actor } from "@qbrix/ui/next/entity";
import { Health } from "@qbrix/ui/next/health";
import { FilterChoice, FilterToggle, List, type ListColumn, type ListGroup } from "@qbrix/ui/next/list";
import { Menu } from "@qbrix/ui/next/menu";
import { ObjectPage, Property, RailSection, type ObjectTab } from "@qbrix/ui/next/object-page";
import { Segmented } from "@qbrix/ui/next/segmented";
import { StateBadge, StateDot } from "@qbrix/ui/next/state";

const CLAUDE: Actor = { kind: "connection", name: "Claude Code", onBehalfOf: "Mustafa" };
const CURSOR: Actor = { kind: "connection", name: "Cursor", onBehalfOf: "Sam" };
const ADA: Actor = { kind: "member", name: "Ada" };
const SAM_API: Actor = { kind: "member", name: "Sam", via: "the API" };
const QBRIX: Actor = { kind: "qbrix" };
const GITHUB: Actor = { kind: "github", name: "#502" };

const TABS: ObjectTab[] = [
  { key: "overview", label: "Overview", href: "#overview" },
  { key: "brief", label: "Brief", href: "#brief" },
  { key: "delivery", label: "Delivery", href: "#delivery" },
  { key: "cycles", label: "Cycles", count: 2, href: "#cycles" },
  { key: "history", label: "History", count: 9, href: "#history" },
];

const PROPOSAL: ChangeData = {
  actor: CLAUDE,
  verb: "proposes a change to",
  target: { kind: "loop", name: "Pricing page CTA", href: "#" },
  diff: [{ field: "options", after: "Annual first" }],
  reason:
    "Annual plans closed 2.4× better from the pricing page in last quarter's sales data. Worth letting the loop test it against the two current options.",
  consequence: "Options are fixed within a cycle, so this starts cycle 3. Cycle 2 seals and keeps its history.",
  proposed: true,
  status: { state: "new", label: "Waiting on you" },
  context: "proposed change",
  time: "2 hours ago",
};

const PROPOSAL_ACTIONS: ChangeActions = {
  approve: { label: "Approve and start cycle 3", onSelect: () => undefined },
  askForChanges: () => undefined,
  decline: () => undefined,
};

type HistoryEntry = { id: string; change: ChangeData; fold?: number; undoable?: boolean };

const HISTORY: ListGroup<HistoryEntry>[] = [
  {
    key: "today",
    label: "Today",
    items: [
      {
        id: "rename",
        undoable: true,
        change: {
          actor: CLAUDE,
          verb: "renamed",
          target: { kind: "loop", name: "Pricing page CTA" },
          diff: [{ field: "name", before: "Pricing page CTA", after: "Pricing CTA" }],
          reason: "Shorter name for the same loop; the old one read like a page.",
          time: "14:02",
        },
      },
      {
        id: "pause",
        undoable: true,
        change: {
          actor: QBRIX,
          verb: "paused",
          target: { kind: "loop", name: "Search ranking" },
          diff: [{ field: "state", before: "live", after: "paused" }],
          reason: "decision errors",
          context: "safety pause",
          time: "03:12",
        },
      },
      {
        id: "fold",
        fold: 6,
        change: {
          actor: CLAUDE,
          verb: "made 6 changes to",
          target: { kind: "loop", name: "Onboarding steps" },
          time: "11:20 to 11:28",
        },
      },
    ],
  },
  {
    key: "yesterday",
    label: "Yesterday",
    items: [
      {
        id: "metric",
        change: {
          actor: CURSOR,
          verb: "created the metric",
          target: { kind: "metric", name: "order_value" },
          diff: [{ field: "metric", after: "order_value · value · 7 days" }],
          time: "10:05",
          tag: { label: "Undone by Mustafa" },
        },
      },
      {
        id: "draft",
        change: {
          actor: SAM_API,
          verb: "created",
          target: { kind: "loop", name: "Checkout headline" },
          diff: [{ field: "loop", after: "draft · 3 options" }],
          time: "09:40",
        },
      },
      {
        id: "moved",
        change: {
          actor: ADA,
          verb: "narrowed the audience of",
          target: { kind: "loop", name: "Checkout headline" },
          diff: [{ field: "audience", before: "everyone", after: "mobile visitors" }],
          time: "09:12",
          tag: { label: "Moved since", href: "#" },
        },
      },
    ],
  },
];

type LoopRow = {
  key: string;
  name: string;
  state: "ok" | "part";
  badge?: string;
  latest: string;
  share: number[];
  shareLabel: string;
  metric: string;
  lift: string;
  actor: Actor;
  when: string;
};

const LOOPS: ListGroup<LoopRow>[] = [
  {
    key: "needs-you",
    label: "Needs you",
    count: 2,
    items: [
      {
        key: "search-ranking",
        name: "Search ranking",
        state: "part",
        latest: "qbrix paused it.",
        share: [44, 31, 25],
        shareLabel: "44% Relevance · frozen",
        metric: "search_clicked",
        lift: "paused · 6 h",
        actor: QBRIX,
        when: "03:12",
      },
      {
        key: "pricing-cta",
        name: "Pricing page CTA",
        state: "ok",
        badge: "Waiting on you",
        latest: "Claude Code proposed a change.",
        share: [52, 48],
        shareLabel: "52% Start free",
        metric: "trial_started",
        lift: "+3.1%",
        actor: CLAUDE,
        when: "2h ago",
      },
    ],
  },
  {
    key: "learning",
    label: "Learning",
    count: 1,
    items: [
      {
        key: "checkout-headline",
        name: "Checkout headline",
        state: "ok",
        latest: "Ada narrowed the audience.",
        share: [58, 27, 15],
        shareLabel: "58% Pay in one tap",
        metric: "checkout_completed",
        lift: "+6.2%",
        actor: ADA,
        when: "4 Oct",
      },
    ],
  },
];

const RAMP = ["bg-n-ink", "bg-n-viz-2", "bg-n-viz-3"];

const LOOP_COLUMNS: ListColumn<LoopRow>[] = [
  {
    key: "loop",
    label: "Loop",
    render: (loop) => (
      <div className="flex gap-3">
        <StateDot state={loop.state} className="mt-[7px]" />
        <div className="flex min-w-0 flex-col gap-1">
          <span className="n-body flex items-center gap-2">
            <LoopRef name={loop.name} />
            {loop.badge && <StateBadge state="new">{loop.badge}</StateBadge>}
          </span>
          <span className="n-body truncate text-n-text-2">{loop.latest}</span>
        </div>
      </div>
    ),
  },
  {
    key: "share",
    label: "Share now",
    width: "150px",
    render: (loop) => (
      <div className="flex flex-col gap-1">
        <div className="flex h-1.5 gap-0.5 overflow-hidden rounded-[3px]">
          {loop.share.map((share, rank) => (
            <span key={rank} className={RAMP[rank]} style={{ width: `${share}%` }} />
          ))}
        </div>
        <span className="n-label font-normal text-n-text-2">{loop.shareLabel}</span>
      </div>
    ),
  },
  {
    key: "metric",
    label: "vs even split",
    width: "140px",
    render: (loop) => (
      <div className="flex flex-col gap-1">
        <span className="n-label font-n-mono font-normal text-n-text-2">{loop.metric}</span>
        <span className="n-body font-medium tabular-nums">{loop.lift}</span>
      </div>
    ),
  },
  {
    key: "last",
    label: "Last change",
    width: "110px",
    render: (loop) => (
      <div className="n-meta flex flex-col gap-0.5">
        <ActorRef actor={loop.actor} />
        <span className="n-label font-normal text-n-text-3">{loop.when}</span>
      </div>
    ),
  },
];

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="n-meta text-n-text-3">{label}</span>
      {children}
    </div>
  );
}

function Frame({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={`flex overflow-hidden rounded-n-panel border border-n-line ${className ?? ""}`}>{children}</div>;
}

export function Modules() {
  const [viewer, setViewer] = useState(false);
  const canEdit = !viewer;

  return (
    <div className="flex flex-col gap-8">
      <FilterToggle icon={Eye} label="As a viewer" pressed={viewer} onChange={setViewer} className="self-start" />

      <Row label="Entity forms: kinds by form, colour only for state">
        <div className="flex flex-col gap-3">
          <p className="n-body flex flex-wrap items-center gap-2">
            <LoopRef name="Checkout headline" href="#" />
            <OptionPill name="Pay in one tap" rank={0} />
            <OptionPill name="Ships today" rank={1} />
            <OptionPill name="Fewer returns" rank={2} />
            <OptionPill name="Others" rank={3} />
            <OptionPill name="Annual first" />
            <MetricRef name="checkout_completed" href="#" />
          </p>
          <p className="n-body flex flex-wrap items-center gap-4">
            <ActorRef actor={ADA} />
            <ActorRef actor={CLAUDE} />
            <ActorRef actor={CLAUDE} withVia />
            <ActorRef actor={SAM_API} withVia />
            <ActorRef actor={QBRIX} />
            <ActorRef actor={GITHUB} />
          </p>
          <p className="n-lead">
            <LoopRef name="Checkout headline" /> <span className="text-n-text-2">is live and learning.</span>
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <StateBadge state="ok">Healthy</StateBadge>
            <StateBadge state="part">Needs attention</StateBadge>
            <StateBadge state="no">Broken</StateBadge>
            <StateBadge state="new">Waiting on you</StateBadge>
            <DiffChip field="name" before="Pricing page CTA" after="Pricing CTA" />
            <DiffChip field="options" after="Annual first" />
            <DiffChip field="options" before="Ships today" />
          </div>
        </div>
      </Row>

      <Row label="ObjectPage and Health: the tabs change the body, the rail stays put">
        <ObjectPageFixture canEdit={canEdit} />
      </Row>

      <Row label="List: columns, grouped, rows that link">
        <LoopListFixture canEdit={canEdit} />
      </Row>

      <Row label="List and Change: history, filters, a selected row, fold, undo and its tags">
        <HistoryFixture canEdit={canEdit} />
      </Row>

      <Row label="Change: inbox">
        <Frame className="bg-n-surface p-8">
          <Change layout="inbox" change={PROPOSAL} actions={PROPOSAL_ACTIONS} canEdit={canEdit}>
            <Note icon={Box}>The screen&apos;s own evidence goes here: now and after, the new option.</Note>
          </Change>
        </Frame>
      </Row>

      <Row label="Change: phone, the same props at 390 wide">
        <Frame className="h-[700px] w-[390px] bg-n-surface">
          <div className="w-full overflow-y-auto">
            <Change layout="phone" change={PROPOSAL} actions={PROPOSAL_ACTIONS} canEdit={canEdit}>
              <Note icon={Box}>The screen&apos;s own evidence goes here: now and after, the new option.</Note>
            </Change>
          </div>
        </Frame>
      </Row>
    </div>
  );
}

function ObjectPageFixture({ canEdit }: { canEdit: boolean }) {
  const [tab, setTab] = useState("overview");
  const label = TABS.find((t) => t.key === tab)?.label;

  const followTab = (e: React.MouseEvent) => {
    const hash = (e.target as HTMLElement).closest("a")?.hash.slice(1);
    if (TABS.some((t) => t.key === hash)) setTab(hash as string);
  };

  return (
    <div onClick={followTab}>
      <Frame>
        <ObjectPage
          crumbs={[{ label: "Loops", href: "#" }, { label: "Checkout headline" }]}
          tabs={TABS}
          activeTab={tab}
          canEdit={canEdit}
          viewOnly="Ask Ada or Mustafa to change this loop"
          actions={
            <>
              <Button size="sm">Commit</Button>
              <Button variant="secondary" size="sm">
                <Pause size={12} />
                Pause
              </Button>
            </>
          }
          menu={
            <Menu
              items={[
                { label: "Copy link", onSelect: () => undefined },
                { label: "Retire", consequence: "Its history stays", tone: "danger", canEdit, onSelect: () => undefined },
              ]}
            />
          }
          rail={
            <>
              <RailSection title="Loop">
                <Property label="State" value="Live" state="ok" />
                <Property label="Cycle" value="2 of 2" />
                <Property label="Engine" value="Spinoza 1.3" />
                <Property label="Metric" value={<MetricRef name="checkout_completed" href="#" />} />
                <Property label="Window" value="24 hours" />
              </RailSection>
              <Health
                signals={[
                  { label: "Decision errors", value: "0.02%", state: "ok" },
                  { label: "Outcomes arriving", value: "12s ago", state: "part" },
                  { label: "Outcomes learned", value: "—", state: "no" },
                  { label: "Approvals", value: "1", state: "new" },
                  { label: "Waiting to seal", value: "214" },
                ]}
              />
              <AskYourAgent label="Ask your agent · about what's happening" prompts={["Why is Ships today losing share?"]} className="mt-auto" />
            </>
          }
        >
          <div className="flex min-h-[320px] flex-col gap-2">
            <h3 className="n-lead">{label}</h3>
            <p className="n-body text-n-text-2">The four-part header and this tab&apos;s evidence go here.</p>
          </div>
        </ObjectPage>
      </Frame>
    </div>
  );
}

function LoopListFixture({ canEdit }: { canEdit: boolean }) {
  const [order, setOrder] = useState("needs");
  const [empty, setEmpty] = useState(false);
  const [picked, setPicked] = useState("checkout-headline");

  return (
    <div className="flex flex-col gap-6">
      <List
        groups={empty ? [] : LOOPS}
        columns={LOOP_COLUMNS}
        rowKey={(loop) => loop.key}
        rowLabel={(loop) => loop.name}
        href={() => "#"}
        canEdit={canEdit}
        actions={<Button size="sm">New loop</Button>}
        controls={
          <>
            <FilterChoice
              label="Order"
              value={order}
              onChange={setOrder}
              options={[
                { value: "needs", label: "What needs a person" },
                { value: "recent", label: "Latest change" },
              ]}
            />
            <FilterToggle label="No loops" pressed={empty} onChange={setEmpty} />
          </>
        }
        empty={<p className="n-body text-n-text-2">No loops match.</p>}
      />
      <List
        items={LOOPS.flatMap((group) => group.items)}
        columns={LOOP_COLUMNS.slice(0, 2)}
        rowKey={(loop) => loop.key}
        rowLabel={(loop) => `Select ${loop.name}`}
        onSelect={(loop) => setPicked(loop.key)}
        selected={(loop) => loop.key === picked}
      />
    </div>
  );
}

function HistoryFixture({ canEdit }: { canEdit: boolean }) {
  const [who, setWho] = useState("everyone");
  const [kind, setKind] = useState("any");
  const [canUndo, setCanUndo] = useState(false);
  const [selected, setSelected] = useState("rename");
  const [open, setOpen] = useState(false);

  return (
    <List
      groups={HISTORY}
      rowKey={(entry) => entry.id}
      controls={
        <>
          <Segmented
            label="Who"
            value={who}
            onChange={setWho}
            options={[
              { value: "everyone", label: "Everyone", count: 53 },
              { value: "people", label: "People", count: 9 },
              { value: "agents", label: "Agents", count: 41 },
              { value: "qbrix", label: "qbrix", count: 3 },
            ]}
          />
          <FilterChoice
            label="Kind"
            icon={Tag}
            value={kind}
            onChange={setKind}
            options={[
              { value: "any", label: "Kind" },
              { value: "loop.rename", label: "loop.rename", count: 4 },
              { value: "loop.pause", label: "loop.pause", count: 1 },
            ]}
          />
          <FilterToggle label="Can undo" icon={Undo2} pressed={canUndo} onChange={setCanUndo} />
        </>
      }
      renderRow={(entry) => (
        <Change
          layout="history"
          change={entry.change}
          canEdit={canEdit}
          actions={entry.undoable ? { undo: () => undefined } : undefined}
          selected={selected === entry.id}
          onSelect={() => setSelected(entry.id)}
          fold={entry.fold ? { label: `Show all ${entry.fold}`, expanded: open, onToggle: () => setOpen((v) => !v) } : undefined}
        />
      )}
    />
  );
}
