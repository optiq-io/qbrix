import type { ChangeCounts } from "@/lib/api/types";
import type { EyebrowToken } from "@/lib/header/status";
import { WHO_WORDS, type ChangeWho } from "./filter";

function counted(count: number, text: string): EyebrowToken[] {
  return [
    { kind: "counter", value: String(count) },
    { kind: "text", text },
  ];
}

function changes(count: number) {
  return count === 1 ? "change" : "changes";
}

/** the who option narrows total, undone and clients; it never narrows counts.who */
export function changesEyebrow(counts: ChangeCounts, who: ChangeWho | null): EyebrowToken[][] {
  const undone = counted(counts.undone, " undone");
  if (!who) {
    return [
      counted(counts.total, ` ${changes(counts.total)} this week`),
      counted(counts.who.connection, " by agents"),
      counted(counts.who.member, " by people"),
      counted(counts.who.qbrix, " by qbrix"),
      undone,
    ];
  }
  const lead = counted(counts.total, ` ${changes(counts.total)} by ${WHO_WORDS[who]} this week`);
  if (who !== "connection") return [lead, undone];
  const clients = counts.clients.map(({ name, count }): EyebrowToken[] => [
    { kind: "text", text: `${name} ` },
    { kind: "counter", value: String(count) },
  ]);
  return [lead, ...clients, undone];
}

export function whoCounts(counts: ChangeCounts | undefined) {
  if (!counts) return { everyone: undefined, member: undefined, connection: undefined, qbrix: undefined };
  const { member, connection, qbrix } = counts.who;
  return { everyone: member + connection + qbrix, member, connection, qbrix };
}
