import type { Connection } from "@/lib/api/types";
import { ago } from "../loop/fact";

const DAY = 24 * 60 * 60 * 1000;

/** the proxy stops renewing a connection this long after its last use */
const UNUSED_LIMIT = 90 * DAY;
const ENDING_WITHIN = 30 * DAY;

export type ConnectionHealth = "healthy" | "ending";

export function endsAt(connection: Connection): number {
  return Date.parse(connection.last_used_at ?? connection.created_at) + UNUSED_LIMIT;
}

export function connectionHealth(connection: Connection, now: number): ConnectionHealth {
  return endsAt(connection) - now <= ENDING_WITHIN ? "ending" : "healthy";
}

export function endsOn(connection: Connection): string {
  return new Date(endsAt(connection)).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function connectionNote(connection: Connection, now: number): string {
  if (connectionHealth(connection, now) === "ending") return `ends ${endsOn(connection)}`;
  return connection.last_used_at ? `used ${ago(connection.last_used_at, now)}` : "not used yet";
}

/** an admin's list holds everyone's connections; yours are the ones acting for you */
export function yours(connections: Connection[], userId: string | undefined): Connection[] {
  return connections.filter((connection) => connection.user.id === userId);
}

export function plugHealth(connections: Connection[], now: number): ConnectionHealth {
  return connections.some((connection) => connectionHealth(connection, now) === "ending") ? "ending" : "healthy";
}
