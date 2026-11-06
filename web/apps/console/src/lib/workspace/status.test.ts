import { describe, expect, it } from "vitest";
import type { WorkspaceStatus } from "@/lib/api/types";
import { statusProblem } from "./status";

function status(overrides: {
  services?: Partial<WorkspaceStatus["services"]>;
  learning?: Partial<WorkspaceStatus["learning"]>;
} = {}): WorkspaceStatus {
  return {
    version: "0.5.0",
    services: { storage: true, deciding: true, learning: true, ...overrides.services },
    learning: { lag_ms: 4_000, checked_at: "2026-11-05T12:00:00+00:00", behind: false, ...overrides.learning },
  };
}

describe("statusProblem", () => {
  it("says nothing while everything answers and learning keeps up", () => {
    expect(statusProblem(status())).toBeNull();
  });

  it("names the first service that doesn't answer", () => {
    expect(statusProblem(status({ services: { storage: false, learning: false } }))).toBe(
      "Storage isn't answering",
    );
    expect(statusProblem(status({ services: { deciding: false, learning: false } }))).toBe(
      "Deciding isn't answering",
    );
    expect(statusProblem(status({ services: { learning: false } }))).toBe("Learning isn't answering");
  });

  it("says how far behind learning is", () => {
    expect(statusProblem(status({ learning: { lag_ms: 6 * 60_000, behind: true } }))).toBe(
      "Learning is 6 minutes behind",
    );
  });

  it("says learning is behind when it left no progress to measure", () => {
    expect(statusProblem(status({ learning: { lag_ms: null, checked_at: null, behind: true } }))).toBe(
      "Learning is behind",
    );
  });
});
