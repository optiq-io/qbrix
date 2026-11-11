import { describe, expect, it } from "vitest";
import type { Connection } from "@/lib/api/types";
import { connectionHealth, connectionNote, endsOn, plugHealth, yours } from "./health";

const DAY = 24 * 60 * 60 * 1000;
const NOW = Date.UTC(2026, 10, 5, 12);

function connection(lastUsedDaysAgo: number | null, overrides: Partial<Connection> = {}): Connection {
  return {
    id: "c1",
    client: { name: "Claude Code", uri: null, identity: "claude-code" },
    user: { id: "u1", name: "Ada" },
    created_at: new Date(NOW - 100 * DAY).toISOString(),
    last_used_at: lastUsedDaysAgo === null ? null : new Date(NOW - lastUsedDaysAgo * DAY).toISOString(),
    levels_changed: [],
    ...overrides,
  };
}

describe("connectionHealth", () => {
  it("is healthy while more than 30 days remain", () => {
    expect(connectionHealth(connection(59), NOW)).toBe("healthy");
  });

  it("is ending from 30 days before its end", () => {
    expect(connectionHealth(connection(60), NOW)).toBe("ending");
  });

  it("counts from creation when it was never used", () => {
    const fresh = connection(null, { created_at: new Date(NOW - DAY).toISOString() });
    expect(connectionHealth(fresh, NOW)).toBe("healthy");
    expect(connectionHealth(connection(null), NOW)).toBe("ending");
  });
});

describe("connectionNote", () => {
  it("names the last use while healthy", () => {
    expect(connectionNote(connection(0), NOW)).toBe("used 0 seconds ago");
    expect(connectionNote(connection(2), NOW)).toBe("used 2 days ago");
  });

  it("names the day it ends once it is ending", () => {
    expect(connectionNote(connection(80), NOW)).toBe(`ends ${endsOn(connection(80))}`);
    expect(endsOn(connection(80))).toBe("15 Nov");
  });
});

describe("yours and plugHealth", () => {
  it("keeps only the connections acting for you", () => {
    const list = [connection(1), connection(1, { id: "c2", user: { id: "u2", name: "Ben" } })];
    expect(yours(list, "u1").map((c) => c.id)).toEqual(["c1"]);
  });

  it("turns the plug amber when any of yours is ending", () => {
    expect(plugHealth([connection(1)], NOW)).toBe("healthy");
    expect(plugHealth([connection(1), connection(70)], NOW)).toBe("ending");
    expect(plugHealth([], NOW)).toBe("healthy");
  });
});
