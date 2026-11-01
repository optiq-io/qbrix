import { format, isSameDay } from "date-fns";
import type { ChangeData, ChangeDiff, ChangeTarget } from "@qbrix/ui/next/change";
import { actorName, type Actor } from "@qbrix/ui/next/entity";
import type { SharePin } from "@qbrix/ui/next/share-chart";
import type { RailEntry } from "@qbrix/ui/next/time-rail";
import type { ChangeActorMark, ChangeEntry } from "@/lib/api/types";
import type { HeaderEvent, Token } from "@/lib/header/token";

const QBRIX: Actor = { kind: "qbrix" };

function toActor(mark: ChangeActorMark | null): Actor {
  if (mark?.kind === "connection") {
    return { kind: "connection", name: mark.name ?? "a client", onBehalfOf: mark.on_behalf_of ?? "someone" };
  }
  if (mark?.kind === "member") {
    return { kind: "member", name: mark.name ?? "Someone", via: mark.via ?? undefined };
  }
  return QBRIX;
}

function actorOf(entry: ChangeEntry): Actor {
  return toActor(entry.pieces.find((piece) => piece.kind === "actor")?.actor ?? null);
}

function tokens(entry: ChangeEntry): Token[] {
  return entry.pieces.map((piece): Token => {
    if (piece.kind === "actor") return { kind: "actor", actor: toActor(piece.actor) };
    if (piece.kind === "text") return { kind: "text", text: piece.text ?? "" };
    return { kind: piece.kind, name: piece.name ?? "" };
  });
}

function differences(entry: ChangeEntry): ChangeDiff[] {
  return entry.diff.map(({ field, before, after }) => ({
    field,
    before: before ?? undefined,
    after: after ?? undefined,
  }));
}

function atMs(entry: ChangeEntry): number {
  return entry.at ? Date.parse(entry.at) : 0;
}

/** an alert reads as what happened and its stored reason, with no chips or quote */
export function toHeaderEvent(entry: ChangeEntry, alert = false): HeaderEvent {
  const reason = entry.reason ?? undefined;
  return {
    id: entry.id,
    kind: entry.kind,
    at: atMs(entry),
    firstAt: entry.count > 1 && entry.first_at ? Date.parse(entry.first_at) : undefined,
    pieces: tokens(entry),
    diff: alert ? [] : differences(entry),
    reason: alert ? undefined : reason,
    context: alert ? reason : undefined,
    source: actorName(actorOf(entry)),
    alert: alert || undefined,
  };
}

function targetOf(entry: ChangeEntry): ChangeTarget {
  const named = entry.pieces.find((piece) => piece.kind === "loop" || piece.kind === "metric");
  if (named?.name) return { kind: named.kind as "loop" | "metric", name: named.name };
  const texts = entry.pieces.filter((piece) => piece.kind === "text");
  return { kind: "other", name: texts[1]?.text?.trim() ?? "" };
}

function verbOf(entry: ChangeEntry): string {
  return entry.pieces.find((piece) => piece.kind === "text")?.text?.trim() ?? "";
}

export function toChangeData(entry: ChangeEntry, now: number): ChangeData {
  const at = atMs(entry);
  const undoer = entry.undone_by;
  return {
    actor: actorOf(entry),
    verb: verbOf(entry),
    target: targetOf(entry),
    diff: differences(entry),
    reason: entry.reason ?? undefined,
    // the rail already says the time of a change made today
    time: isSameDay(at, now) ? "" : format(at, "HH:mm"),
    tag: undoer ? { label: `Undone by ${undoer.who.name ?? "qbrix"}` } : undefined,
  };
}

export function toRailEntry(entry: ChangeEntry, cycleStart: number, now: number): RailEntry {
  const at = atMs(entry);
  return {
    key: entry.id,
    kind: entry.kind === "loop.create" ? "origin" : entry.kind === "loop.pause" ? "pause" : "tick",
    at: isSameDay(at, now) ? format(at, "HH:mm") : format(at, "d MMM"),
    state: at >= cycleStart ? "live" : "sealed",
  };
}

function sentence(entry: ChangeEntry): string {
  return entry.pieces
    .map((piece) => (piece.kind === "actor" ? actorName(toActor(piece.actor)) : (piece.text ?? piece.name ?? "")))
    .join("");
}

function moved({ before, after }: ChangeEntry["diff"][number]): string {
  if (before !== null && after !== null) return `${before} → ${after}`;
  return after !== null ? `+ ${after}` : `− ${before}`;
}

export function toPin(entry: ChangeEntry): SharePin {
  const at = atMs(entry);
  return {
    at,
    entryId: entry.id,
    actor: actorOf(entry),
    title: sentence(entry),
    detail: [...entry.diff.map(moved), format(at, "d MMM")].join("  ·  "),
  };
}
