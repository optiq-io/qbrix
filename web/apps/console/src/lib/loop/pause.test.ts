import { describe, expect, it } from "vitest";
import type { ChangeEntry, DecisionErrorEvidence, LoopResults } from "@/lib/api/types";
import { pausedErrors, pausedFor, pauseOf, pauseRows, resumeConsequence, type Pause } from "./pause";

const NOW = new Date(2026, 9, 30, 9, 41).getTime();
const AT = new Date(2026, 9, 30, 3, 12);

const EVIDENCE: DecisionErrorEvidence = {
  signal: "decision_errors",
  rate: 0.0903,
  errors: 112,
  calls: 1240,
  window_start: new Date(2026, 9, 30, 3, 3).toISOString(),
  window_end: new Date(2026, 9, 30, 3, 12, 20).toISOString(),
  reasons: { store: 8, motor_timeout: 104 },
};

function change(overrides: Partial<ChangeEntry> = {}): ChangeEntry {
  return {
    id: "pause",
    kind: "loop.pause",
    at: AT.toISOString(),
    status: "applied",
    reason: "decision errors",
    evidence: EVIDENCE,
    pieces: [
      { kind: "actor", actor: { kind: "qbrix", name: null, on_behalf_of: null, via: null }, text: null, name: null },
      { kind: "text", actor: null, text: " paused it.", name: null },
    ],
    diff: [],
    undone_by: null,
    count: 1,
    first_at: AT.toISOString(),
    ...overrides,
  };
}

const PAUSE: Pause = { id: "pause", at: AT.getTime(), byQbrix: true, evidence: EVIDENCE };
const RESULTS = { calls: { live: 0, draft: 0, paused: 214 } } as LoopResults;

describe("pauseOf", () => {
  it("reads a safety pause", () => {
    expect(pauseOf({ state: "paused" }, [change()])).toEqual(PAUSE);
  });

  it("finds the pause behind a later rename", () => {
    const renamed = change({ id: "rename", kind: "loop.rename", evidence: null });
    expect(pauseOf({ state: "paused" }, [renamed, change()])?.id).toBe("pause");
  });

  it("takes the newest of several pauses", () => {
    const earlier = change({ id: "earlier" });
    expect(pauseOf({ state: "paused" }, [change(), earlier])?.id).toBe("pause");
  });

  it("is nothing once the loop is live again", () => {
    expect(pauseOf({ state: "live" }, [change()])).toBeNull();
  });

  it("is nothing when no pause is in the changes", () => {
    expect(pauseOf({ state: "paused" }, [change({ kind: "loop.rename" })])).toBeNull();
  });

  it("reads a person's pause as having no evidence", () => {
    const person = change({
      evidence: null,
      pieces: [
        { kind: "actor", actor: { kind: "member", name: "Ada", on_behalf_of: null, via: null }, text: null, name: null },
      ],
    });
    expect(pauseOf({ state: "paused" }, [person])).toMatchObject({ byQbrix: false, evidence: null });
  });

  it("ignores evidence for a signal it doesn't know", () => {
    const other = change({ evidence: { signal: "outcomes_stopped" } });
    expect(pauseOf({ state: "paused" }, [other])?.evidence).toBeNull();
  });
});

describe("pauseRows", () => {
  it("reads the evidence, with the largest reason first", () => {
    expect(pauseRows(PAUSE, "Relevance", RESULTS)).toEqual([
      { label: "Signal", value: "decision errors" },
      { label: "Rule", value: "over 5% of at least 100 calls, in 10 minutes" },
      { label: "At pause", value: "9.0% · 112 of 1,240 · motor timeout 104 · store 8" },
      { label: "While paused", value: "answered with Relevance · 214 calls, last hour" },
    ]);
  });

  it("says how long the window was when it's shorter than the rule's", () => {
    const evidence = { ...EVIDENCE, window_end: new Date(2026, 9, 30, 3, 5, 30).toISOString() };
    const row = pauseRows({ ...PAUSE, evidence }, "Relevance", RESULTS).find(({ label }) => label === "At pause");
    expect(row?.value).toMatch(/ · over 3 minutes$/);
  });

  it("leaves the count out until results load", () => {
    expect(pauseRows(PAUSE, "Relevance", undefined).at(-1)?.value).toBe("answered with Relevance");
  });

  it("has no rows without evidence", () => {
    expect(pauseRows({ ...PAUSE, evidence: null }, "Relevance", RESULTS)).toEqual([]);
    expect(pauseRows(null, "Relevance", RESULTS)).toEqual([]);
  });
});

describe("pausedFor", () => {
  it("reads hours and minutes since a time today", () => {
    expect(pausedFor(PAUSE, NOW)).toEqual({ value: "6 h 29 m", caption: "since 03:12" });
  });

  it("reads minutes alone under an hour", () => {
    expect(pausedFor(PAUSE, AT.getTime() + 4 * 60_000)).toMatchObject({ value: "4 m" });
  });

  it("names the day of an older pause", () => {
    const later = new Date(2026, 10, 2, 5, 12).getTime();
    expect(pausedFor(PAUSE, later)).toEqual({ value: "3 d 2 h", caption: "since 30 Oct 03:12" });
  });
});

describe("pausedErrors", () => {
  it("shows the rate at the pause as needing a look, never a healthy zero", () => {
    expect(pausedErrors(PAUSE)).toEqual({ label: "Decision errors", value: "9.0% at pause", state: "part" });
  });

  it("is a dash without evidence", () => {
    expect(pausedErrors({ ...PAUSE, evidence: null })).toEqual({ label: "Decision errors", value: "—" });
  });
});

describe("resumeConsequence", () => {
  it("names the cycle and the pause's time", () => {
    expect(resumeConsequence(2, PAUSE, NOW)).toEqual({
      title: "Resuming continues cycle 2 where it left off.",
      body: "Outcomes for decisions made before 03:12 still count as they arrive. qbrix never resumes on its own.",
    });
  });

  it("still reads when the pause isn't in the changes", () => {
    expect(resumeConsequence(2, null, NOW).body).toContain("made before the pause still");
  });
});
