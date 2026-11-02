import { format, isSameDay, isSameYear, subDays } from "date-fns";
import type { ChangeData } from "@qbrix/ui/next/change";
import type { ListGroup } from "@qbrix/ui/next/list";
import type { ChangeEntry } from "@/lib/api/types";
import { actorOf, toChangeData } from "../loop/event";
import { isDecisionErrors } from "../loop/pause";

const CLOCK = "HH:mm";

function atMs(entry: ChangeEntry): number {
  return entry.at ? Date.parse(entry.at) : 0;
}

function clock(entry: ChangeEntry): string {
  const end = format(atMs(entry), CLOCK);
  if (entry.count <= 1 || !entry.first_at) return end;
  return `${format(Date.parse(entry.first_at), CLOCK)} to ${end}`;
}

function context(entry: ChangeEntry): string | undefined {
  const actor = actorOf(entry);
  if (actor.kind === "qbrix") return isDecisionErrors(entry.evidence) ? "safety pause" : undefined;
  return actor.kind === "member" && !actor.via ? "in the console" : undefined;
}

export function toHistoryRow(entry: ChangeEntry, now: number): ChangeData {
  return { ...toChangeData(entry, now), time: clock(entry), context: context(entry) };
}

/** a fold has no Undo of its own: an older change in it is usually refused as moved */
export function canUndo(entry: ChangeEntry): boolean {
  return entry.undoable && entry.count === 1 && !entry.undone_by;
}

export function undoLabel(entry: ChangeEntry): string {
  return `Undo ${entry.kind.split(".").pop()}`;
}

function dayLabel(at: number, now: number): string {
  if (isSameDay(at, now)) return "Today";
  if (isSameDay(at, subDays(now, 1))) return "Yesterday";
  return format(at, isSameYear(at, now) ? "EEEE d MMM" : "EEEE d MMM yyyy");
}

export function panelTime(entry: ChangeEntry, now: number): string {
  const at = atMs(entry);
  const day = isSameDay(at, now) ? "Today" : isSameDay(at, subDays(now, 1)) ? "Yesterday" : format(at, "d MMM");
  return entry.count > 1 ? `${day}, ${clock(entry)}` : `${day} at ${clock(entry)}`;
}

export function byDay<T>(items: T[], entryOf: (item: T) => ChangeEntry, now: number): ListGroup<T>[] {
  const groups: ListGroup<T>[] = [];
  for (const item of items) {
    const at = atMs(entryOf(item));
    const key = format(at, "yyyy-MM-dd");
    const last = groups[groups.length - 1];
    if (last?.key === key) last.items.push(item);
    else groups.push({ key, label: dayLabel(at, now), items: [item] });
  }
  return groups;
}
