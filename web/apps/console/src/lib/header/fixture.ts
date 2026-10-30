import type { FactValue } from "./fact";
import type { StatusSubject } from "./status";
import type { HeaderEvent, Token } from "./token";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export type HeaderFixture = {
  key: string;
  name?: string;
  subject: StatusSubject;
  counters: Record<string, string>;
  values: Record<string, FactValue>;
  events: (now: number) => HeaderEvent[];
};

const QBRIX: Token = { kind: "actor", actor: { kind: "qbrix" } };
const SAM: Token = { kind: "actor", actor: { kind: "member", name: "Sam" } };
const text = (value: string): Token => ({ kind: "text", text: value });
const option = (name: string, rank: number): Token => ({ kind: "option", name, rank });

export function leaderChanged(id: string, at: number): HeaderEvent {
  return {
    id,
    kind: "loop.leader_changed",
    at,
    source: "qbrix",
    pieces: [option("Pay in one tap", 0), text(" took the lead from "), option("Ships today", 1), text(".")],
  };
}

export function paused(id: string, at: number, alert = true): HeaderEvent {
  return {
    id,
    kind: "loop.pause",
    at,
    alert,
    source: "qbrix",
    context: "decision errors",
    pieces: [QBRIX, text(" paused it.")],
    diff: [{ field: "state", before: "live", after: "paused" }],
  };
}

function launched(id: string, at: number): HeaderEvent {
  return { id, kind: "loop.launch", at, source: "Sam", pieces: [SAM, text(" launched it with three options.")] };
}

function renamed(id: string, at: number): HeaderEvent {
  return {
    id,
    kind: "loop.rename",
    at,
    source: "Claude Code",
    reason: "The old name read as a test, not a place in the product.",
    pieces: [
      { kind: "actor", actor: { kind: "connection", name: "Claude Code", onBehalfOf: "Mustafa" } },
      text(" renamed "),
      { kind: "loop", name: "Pricing page CTA", href: "#" },
      text("."),
    ],
    diff: [{ field: "name", before: "Pricing test", after: "Pricing page CTA" }],
  };
}

const LIVE_VALUES: Record<string, FactValue> = { ahead: "Pay in one tap", share: "58%", lift: "+6.2%", waiting: "214" };
const LIVE_COUNTERS = { rate: "38", learned: "40 seconds ago" };

export const FIXTURES: HeaderFixture[] = [
  {
    key: "live",
    name: "Checkout headline",
    subject: { kind: "loop", status: "live" },
    counters: LIVE_COUNTERS,
    values: LIVE_VALUES,
    events: (now) => [
      leaderChanged("leader", now - 2 * DAY),
      renamed("rename", now - 3 * DAY),
      launched("launch", now - 4 * DAY),
      renamed("older-rename", now - 5 * DAY),
    ],
  },
  {
    key: "live-with-alert",
    name: "Checkout headline",
    subject: { kind: "loop", status: "live", alert: true },
    counters: LIVE_COUNTERS,
    values: LIVE_VALUES,
    events: (now) => [
      paused("alert", now - 2 * HOUR),
      leaderChanged("leader", now - HOUR),
      renamed("rename", now - DAY),
      launched("launch", now - 2 * DAY),
    ],
  },
  {
    key: "waiting-on-you",
    name: "Checkout headline",
    subject: { kind: "loop", status: "live", asks: true },
    counters: LIVE_COUNTERS,
    values: LIVE_VALUES,
    events: (now) => [leaderChanged("leader", now - 2 * DAY)],
  },
  {
    key: "warming-up",
    name: "Checkout headline",
    subject: { kind: "loop", status: "warming_up" },
    counters: { rate: "16", learned: "12 seconds ago" },
    values: { decisions: "1,920", outcomes: "312", firstSeal: "tomorrow 14:00" },
    events: (now) => [launched("launch", now - 20 * MINUTE)],
  },
  {
    key: "before-first-data",
    name: "Checkout headline",
    subject: { kind: "loop", status: "warming_up" },
    counters: { rate: "0", learned: "40 seconds ago" },
    values: {
      decisions: { value: "0", caption: "select with checkout-headline" },
      outcomes: { value: "0", caption: "checkout_completed" },
      firstSeal: { value: "—", caption: "24 h after the first decision" },
    },
    events: (now) => [launched("launch", now - 40_000)],
  },
  {
    key: "draft",
    name: "Checkout headline",
    subject: { kind: "loop", status: "draft" },
    counters: { calls: "214" },
    values: { calls: "214", serving: "Fewer returns", ready: "4 of 4" },
    events: (now) => [
      {
        id: "first-call",
        kind: "loop.first_call",
        at: now - 47 * MINUTE,
        source: "#488",
        pieces: [text("The first select call arrived, from #488.")],
      },
      renamed("rename", now - 3 * HOUR),
      renamed("older-rename", now - DAY),
    ],
  },
  {
    key: "paused",
    name: "Search ranking",
    subject: { kind: "loop", status: "paused", alert: true },
    counters: { learned: "4 minutes ago" },
    values: {
      serving: "Relevance",
      pausedFor: { value: "6 h 29 m", caption: "since 03:12" },
      failingNow: "0.2%",
    },
    events: (now) => [
      paused("alert", now - 6.5 * HOUR),
      leaderChanged("leader", now - 2 * DAY),
      renamed("rename", now - 3 * DAY),
    ],
  },
  {
    key: "retired",
    name: "Winter banner",
    subject: { kind: "loop", status: "retired" },
    counters: { retired: "3 Oct" },
    values: { lastAhead: "Free returns", decisions: "1.2M", ranFor: "41 days" },
    events: (now) => [
      {
        id: "retire",
        kind: "loop.retire",
        at: now - 27 * DAY,
        source: "Ada",
        pieces: [{ kind: "actor", actor: { kind: "member", name: "Ada" } }, text(" retired it.")],
        diff: [{ field: "state", before: "live", after: "retired" }],
      },
    ],
  },
  {
    key: "workspace-needs-a-look",
    subject: { kind: "workspace", loops: 4, alerts: 1, asks: 1 },
    counters: { loops: "4", rate: "1,240" },
    values: { learning: "3", warmingUp: "0", paused: "1", drafts: "0" },
    events: (now) => [
      {
        ...paused("alert", now - 6.5 * HOUR),
        pieces: [QBRIX, text(" paused "), { kind: "loop", name: "Search ranking", href: "#" }, text(".")],
        context: undefined,
      },
      leaderChanged("leader", now - 2 * DAY),
      renamed("rename", now - 2 * DAY - HOUR),
      launched("launch", now - 3 * DAY),
      renamed("older-rename", now - 4 * DAY),
    ],
  },
  {
    key: "workspace-waiting",
    subject: { kind: "workspace", loops: 4, alerts: 0, asks: 1 },
    counters: { loops: "4", rate: "1,240" },
    values: { learning: "4", warmingUp: "0", paused: "0", drafts: "0" },
    events: (now) => [renamed("rename", now - 2 * HOUR)],
  },
  {
    key: "workspace-learning",
    subject: { kind: "workspace", loops: 1, alerts: 0, asks: 0 },
    counters: { loops: "1", rate: "38" },
    values: { learning: "1", warmingUp: "0", paused: "0", drafts: "0" },
    events: (now) => [launched("launch", now - 9 * DAY), renamed("rename", now - 12 * DAY)],
  },
  {
    key: "workspace-none",
    subject: { kind: "workspace", loops: 0, alerts: 0, asks: 0 },
    counters: { loops: "0", rate: "0" },
    values: {},
    events: () => [],
  },
  {
    key: "metrics-arriving",
    subject: { kind: "metrics", count: 4, alerts: 0 },
    counters: { count: "4", updated: "10 seconds ago" },
    values: { arriving: "4", outcomes: "2,310", learnedFrom: "98.1%" },
    events: () => [],
  },
  {
    key: "metrics-none",
    subject: { kind: "metrics", count: 0, alerts: 0 },
    counters: { count: "0", rate: "0" },
    values: {},
    events: () => [],
  },
  {
    key: "metric-arriving",
    name: "checkout_completed",
    subject: { kind: "metric", arriving: true },
    counters: { rate: "38", version: "3" },
    values: {
      window: { value: "24 hours", caption: "conversion" },
      halfArrive: "40 min",
      mostArrive: "11 h",
      learnedFrom: "98.7%",
    },
    events: (now) => [
      {
        id: "semantic",
        kind: "metric.version",
        at: now - 2 * DAY,
        source: "#502",
        pieces: [text("#502 changed its semantic.")],
      },
    ],
  },
];

export function fixture(key: string): HeaderFixture {
  const found = FIXTURES.find((entry) => entry.key === key);
  if (!found) throw new Error(`no header fixture "${key}"`);
  return found;
}
