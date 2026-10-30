import { format, isSameDay } from "date-fns";
import type { HeaderEvent } from "./token";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;

export const ENTRANCE_MS = 10_000;

export type PickedItems = {
  /** in stepping order; the first is the one to show */
  set: HeaderEvent[];
  pinned: boolean;
  inWeek: boolean;
};

/** unresolved alerts oldest first, then the week's events newest first; with neither, every event */
export function pickItem(events: HeaderEvent[], now: number): PickedItems {
  const alerts = events.filter((event) => event.alert).sort((a, b) => a.at - b.at);
  const rest = events.filter((event) => !event.alert).sort((a, b) => b.at - a.at);
  const recent = rest.filter((event) => now - event.at < WEEK);

  if (alerts.length === 0 && recent.length === 0) return { set: rest, pinned: false, inWeek: false };
  return { set: [...alerts, ...recent], pinned: alerts.length > 0, inWeek: true };
}

export function counter({ set, inWeek }: PickedItems, shownId: string | null): string | null {
  const at = set.findIndex((event) => event.id === shownId);
  if (at < 0) return null;
  return `${at + 1} of ${set.length}${inWeek ? " this week" : ""}`;
}

function clock(at: number) {
  return format(at, "HH:mm");
}

function plural(count: number, unit: string) {
  return `${count} ${unit}${count === 1 ? "" : "s"} ago`;
}

function eventTime(event: HeaderEvent, now: number): string {
  if (event.firstAt !== undefined) return `${clock(event.firstAt)} to ${clock(event.at)}`;
  if (event.alert) return isSameDay(event.at, now) ? clock(event.at) : format(event.at, "d MMM");

  const age = now - event.at;
  if (age < MINUTE) return "just now";
  if (age < HOUR) return plural(Math.floor(age / MINUTE), "minute");
  if (age < DAY) return plural(Math.floor(age / HOUR), "hour");
  if (age < WEEK) return plural(Math.floor(age / DAY), "day");
  return format(event.at, "d MMM");
}

export function itemMeta(event: HeaderEvent, now: number): string[] {
  return [event.source, eventTime(event, now), event.context].filter((part): part is string => Boolean(part));
}

export type ItemState = {
  shownId: string | null;
  /** the person stepped away from the first item; arrivals don't move them */
  stepped: boolean;
  enteredAt: number | null;
};

export function initialItem({ set }: PickedItems): ItemState {
  return { shownId: set[0]?.id ?? null, stepped: false, enteredAt: null };
}

export type Advance = {
  /** the same object when nothing changed */
  state: ItemState;
  entered: boolean;
  /** when to look again, for an item held back by the entrance limit */
  dueAt: number | null;
};

/** at most one entrance every ten seconds. anything arriving in between only moves the
    counter, and the first of the set shows on the next turn. pinning needs no rule of its
    own: an alert sorts ahead of everything that could displace it */
export function advance(state: ItemState, { set }: PickedItems, now: number): Advance {
  const first = set[0]?.id ?? null;
  const present = set.some((event) => event.id === state.shownId);

  if (!present) {
    if (state.shownId === first) return { state, entered: false, dueAt: null };
    const entered = first !== null;
    return { state: { shownId: first, stepped: false, enteredAt: entered ? now : state.enteredAt }, entered, dueAt: null };
  }
  if (state.stepped || state.shownId === first) return { state, entered: false, dueAt: null };

  if (state.enteredAt !== null && now - state.enteredAt < ENTRANCE_MS) {
    return { state, entered: false, dueAt: state.enteredAt + ENTRANCE_MS };
  }
  return { state: { shownId: first, stepped: false, enteredAt: now }, entered: true, dueAt: null };
}

export function step(state: ItemState, { set }: PickedItems, by: 1 | -1): ItemState {
  if (set.length < 2) return state;
  const at = set.findIndex((event) => event.id === state.shownId);
  const next = set[(at + by + set.length) % set.length];
  return { ...state, shownId: next.id, stepped: next.id !== set[0].id };
}
