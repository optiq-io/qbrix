import { format, isSameDay } from "date-fns";
import { actorName, type Actor } from "@qbrix/ui/next/entity";
import { bandShares, rankBands, type ShareBand } from "@qbrix/ui/next/share";
import type { ChangeEntry, LoopLatestChange, LoopListItem } from "@/lib/api/types";
import type { FactValue } from "@/lib/header/fact";
import type { LoopStatus } from "@/lib/header/status";
import { toHeaderEvent } from "./event";
import { rate } from "./fact";
import { pauseOf, type Pause } from "./pause";

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

const STATE_ORDER: Record<LoopListItem["state"], number> = { paused: 0, draft: 1, live: 2 };

function updatedMs(loop: LoopListItem): number {
  return loop.updated_at ? Date.parse(loop.updated_at) : 0;
}

export function orderLoops(loops: LoopListItem[]): LoopListItem[] {
  return [...loops].sort(
    (a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state] || updatedMs(b) - updatedMs(a) || a.key.localeCompare(b.key),
  );
}

export function searchLoops(loops: LoopListItem[], query: string): LoopListItem[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return loops;
  return loops.filter((loop) => loop.name.toLowerCase().includes(needle) || loop.key.toLowerCase().includes(needle));
}

/** the list has no sealed counts, so a live loop warms up until it has a lift */
export function listStatus(loop: Pick<LoopListItem, "state" | "results">): LoopStatus {
  if (loop.state !== "live") return loop.state;
  return loop.results?.lift === null || loop.results?.lift === undefined ? "warming_up" : "live";
}

export type WorkspaceCounts = Record<"learning" | "warmingUp" | "paused" | "drafts", number>;

export function workspaceCounts(loops: LoopListItem[]): WorkspaceCounts {
  const counts: WorkspaceCounts = { learning: 0, warmingUp: 0, paused: 0, drafts: 0 };
  for (const loop of loops) {
    const status = listStatus(loop);
    if (status === "live") counts.learning += 1;
    else if (status === "warming_up") counts.warmingUp += 1;
    else if (status === "paused") counts.paused += 1;
    else if (status === "draft") counts.drafts += 1;
  }
  return counts;
}

export function workspaceFacts(counts: WorkspaceCounts): Record<string, FactValue> {
  return {
    learning: String(counts.learning),
    warmingUp: String(counts.warmingUp),
    paused: String(counts.paused),
    drafts: String(counts.drafts),
  };
}

export function workspaceCounters(loops: LoopListItem[], more: boolean): Record<string, string> {
  const perSecond = loops.reduce((sum, loop) => sum + (loop.results?.decisions_per_second ?? 0), 0);
  return { loops: `${loops.length}${more ? "+" : ""}`, rate: rate(perSecond) };
}

export type ShareSegment = {
  key: string;
  name: string;
  rank: ShareBand["rank"];
  share: number;
  members: { name: string; share: number }[];
};

export function shareSegments(loop: Pick<LoopListItem, "options" | "results">): ShareSegment[] | null {
  const shares = loop.results?.share;
  if (!shares) return null;
  const names = new Map(loop.options.map((option) => [option.key, option.name]));
  const options = shares.map(({ key }) => ({ key, name: names.get(key) ?? key }));
  const column = { at: 0, decisions: shares.map(({ share }) => share ?? 0) };
  const bands = rankBands(options, [column]);
  const split = bandShares(column, bands);
  if (!split) return null;
  return bands.map((band, at) => ({
    key: band.key,
    name: band.name,
    rank: band.rank,
    share: split[at],
    members:
      band.rank === 3
        ? band.members.map((index) => ({ name: options[index].name, share: column.decisions[index] }))
        : [],
  }));
}

export function toListActor(change: LoopLatestChange): Actor {
  if (change.who.kind === "qbrix") return { kind: "qbrix" };
  if (change.via) {
    return { kind: "connection", name: change.via.client ?? "a client", onBehalfOf: change.who.name ?? "someone" };
  }
  return { kind: "member", name: change.who.name ?? "Someone" };
}

export function latestEvent(change: LoopLatestChange): string {
  return `${actorName(toListActor(change))} ${change.verb} it.`;
}

export function rowTime(at: string | null, now: number): string {
  if (!at) return "";
  const ms = Date.parse(at);
  if (isSameDay(ms, now)) return format(ms, "HH:mm");
  return format(ms, now - ms < WEEK_MS ? "EEE" : "d MMM");
}

export function pausesByLoop(loops: LoopListItem[], pauses: ChangeEntry[]): Map<string, Pause> {
  const found = new Map<string, Pause>();
  for (const loop of loops) {
    const pause = pauseOf(
      loop,
      pauses.filter((entry) => entry.target.id === loop.id),
    );
    if (pause) found.set(loop.id, pause);
  }
  return found;
}

export function alertCount(pauses: Map<string, Pause>): number {
  return [...pauses.values()].filter((pause) => pause.byQbrix).length;
}

export function workspaceEvents(recent: ChangeEntry[], pauseEntries: ChangeEntry[], pauses: Map<string, Pause>) {
  const alerts = new Set([...pauses.values()].filter((pause) => pause.byQbrix).map((pause) => pause.id));
  const named = recent.filter((entry) => entry.target.type === "loop" || entry.target.type === "metric");
  const seen = new Set(named.map((entry) => entry.id));
  const older = pauseEntries.filter((entry) => alerts.has(entry.id) && !seen.has(entry.id));
  return [...named, ...older].map((entry) => toHeaderEvent(entry, alerts.has(entry.id)));
}
