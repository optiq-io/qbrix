import { describe, expect, it } from "vitest";
import type { Loop, LoopResults } from "@/lib/api/types";
import {
  chartCaption,
  fallbackName,
  firstSeal,
  healthSignals,
  launchConsequence,
  loopCounters,
  loopFacts,
  nowLine,
  readiness,
  windowLabel,
} from "./fact";

const NOW = new Date(2026, 9, 30, 14, 20).getTime();
const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;
const cycleFrom = (startedAt: number) =>
  ({ id: "c", number: 2, started_at: new Date(startedAt).toISOString() }) as NonNullable<LoopResults["cycle"]>;

function results(overrides: Partial<LoopResults> = {}, startedAt = NOW - 12 * DAY): LoopResults {
  return {
    cycle: cycleFrom(startedAt),
    range: "cycle",
    share: {
      since: new Date(startedAt).toISOString(),
      until: new Date(NOW).toISOString(),
      step_seconds: 60,
      options: [
        { key: "a", name: "Ships today", decisions: 42, share: 0.42, sealed: 30, waiting: 12 },
        { key: "b", name: "Pay in one tap", decisions: 58, share: 0.58, sealed: 40, waiting: 18 },
      ],
      series: [],
    },
    lift: { value: 0.062, early: false, since: "", until: "" },
    calls: { live: 3600, draft: 0, paused: 0 },
    decisions_per_second: 38.4,
    health: {
      decision_errors: 0,
      outcomes: { learned: 90, late: 5, duplicate: 5, earlier_cycle: 0 },
      last_outcome_at: new Date(NOW - 12_000).toISOString(),
      last_learned_at: new Date(NOW - 40_000).toISOString(),
      ledger_lag_ms: 100,
    },
    ...overrides,
  };
}

const LOOP = { metric: { window_seconds: 86_400 } } as Loop;

describe("loopCounters", () => {
  it("reads the rate and when it learned", () => {
    const counters = loopCounters(results(), NOW);
    expect(counters.rate).toBe("38");
    expect(counters.learned).toBe("40 seconds ago");
  });

  it("keeps a decimal below ten, and none when it's whole", () => {
    expect(loopCounters(results({ decisions_per_second: 0.44 }), NOW).rate).toBe("0.4");
    expect(loopCounters(results({ decisions_per_second: 0 }), NOW).rate).toBe("0");
    expect(loopCounters(results({ decisions_per_second: 1 }), NOW).rate).toBe("1");
  });

  it("leaves a loop that hasn't learned to the row's dash", () => {
    const health = { ...results().health, last_learned_at: null };
    expect(loopCounters(results({ health }), NOW).learned).toBeUndefined();
  });
});

describe("loopFacts, live", () => {
  it("is ahead on the largest share of the last 24 hours, and waiting over the cycle", () => {
    const facts = loopFacts("live", LOOP, { cycle: results(), day: results() }, NOW);
    expect(facts.ahead).toBe("Pay in one tap");
    expect(facts.share).toBe("58%");
    expect(facts.waiting).toBe("30");
  });

  it("names nobody when the last day has no decisions", () => {
    const share = { ...results().share!, options: results().share!.options.map((o) => ({ ...o, share: null })) };
    const facts = loopFacts("live", LOOP, { cycle: results(), day: results({ share }) }, NOW);
    expect(facts.ahead).toBeUndefined();
    expect(facts.share).toBeUndefined();
  });

  it("signs lift, marks it early, and has none without a value", () => {
    const read = (lift: LoopResults["lift"]) =>
      loopFacts("live", LOOP, { cycle: results({ lift }), day: undefined }, NOW).lift;
    expect(read({ value: 0.062, early: false, since: "", until: "" })).toBe("+6.2%");
    expect(read({ value: -0.01, early: true, since: "", until: "" })).toEqual({
      value: "−1.0%",
      caption: "early · vs an even split",
    });
    expect(read({ value: null, early: true, since: "", until: "" })).toBeUndefined();
    expect(read(null)).toBeUndefined();
  });
});

describe("firstSeal", () => {
  const withFirstDecision = (at: number) => {
    const base = results({}, at);
    return { ...base, share: { ...base.share!, series: [{ at: new Date(at).toISOString(), decisions: [1, 0] }] } };
  };

  it("is the first decision plus the window", () => {
    expect(firstSeal(withFirstDecision(NOW - 20 * MINUTE), 86_400, NOW)).toBe("tomorrow 14:00");
    expect(firstSeal(withFirstDecision(NOW - 20 * MINUTE), 3_600, NOW)).toBe("15:00");
  });

  it("reads now once that has passed and it hasn't sealed yet", () => {
    expect(firstSeal(withFirstDecision(NOW - 2 * DAY), 86_400, NOW)).toBe("now");
  });

  it("waits on a first decision", () => {
    expect(firstSeal(results(), 86_400, NOW)).toEqual({ value: "—", caption: "24 hours after the first decision" });
  });
});

describe("loopFacts, warming up", () => {
  it("captions outcomes for the hour its counter covers", () => {
    const facts = loopFacts("warming_up", LOOP, { cycle: results(), day: undefined }, NOW);
    expect(facts.decisions).toBe("100");
    expect(facts.outcomes).toEqual({ value: "90", caption: "last hour" });
  });
});

describe("loopFacts, paused", () => {
  const loop = { fallback: "a", options: [{ key: "a", name: "Relevance" }] } as Loop;
  const cycle = results({ calls: { live: 0, draft: 0, paused: 1214 } });
  const pause = { id: "p", at: NOW - 89 * MINUTE, byQbrix: true, evidence: null };

  it("reads what's served, for how long and how many it answered", () => {
    expect(loopFacts("paused", loop, { cycle, day: undefined, pause }, NOW)).toEqual({
      serving: "Relevance",
      pausedFor: { value: "1 h 29 m", caption: "since 12:51" },
      answered: "1,214",
    });
  });

  it("leaves Paused for to a dash when the pause isn't in the changes", () => {
    expect(loopFacts("paused", loop, { cycle, day: undefined, pause: null }, NOW).pausedFor).toBeUndefined();
  });
});

describe("healthSignals", () => {
  it("reads each signal from the counters", () => {
    expect(healthSignals(results(), NOW).map(({ label, value }) => [label, value])).toEqual([
      ["Decision errors", "0%"],
      ["Outcomes arriving", "12 seconds ago"],
      ["Outcomes learned", "90.0%"],
      ["Waiting to seal", "30"],
    ]);
  });

  it("takes a paused loop's errors from the pause, however clean the last hour reads", () => {
    const atPause = { label: "Decision errors", value: "9.0% at pause", state: "part" as const };
    expect(healthSignals(results(), NOW, atPause)[0]).toEqual(atPause);
  });

  it("dashes outcomes before any arrive", () => {
    const health = {
      ...results().health,
      outcomes: { learned: 0, late: 0, duplicate: 0, earlier_cycle: 0 },
      last_outcome_at: null,
    };
    const signals = healthSignals(results({ health }), NOW);
    expect(signals[1]).toEqual({ label: "Outcomes arriving", value: "—", state: undefined });
    expect(signals[2].value).toBe("—");
  });
});

describe("wording", () => {
  it("captions the chart for its range", () => {
    const started = new Date(2026, 9, 3, 14, 0).getTime();
    const r = results({}, started);
    expect(chartCaption(r, "cycle", false)).toBe("cycle 2, 3 Oct to now");
    expect(chartCaption(r, "24h", false)).toBe("cycle 2, last 24 hours");
    expect(chartCaption(r, "cycle", true)).toBe("cycle 2 · by minute since 14:00");
  });

  it("says how far into the cycle it is", () => {
    expect(nowLine("live", cycleFrom(NOW - 11.5 * DAY), NOW)).toBe("Day 12 of cycle 2 · learning");
    expect(nowLine("warming_up", cycleFrom(NOW - 20 * MINUTE), NOW)).toBe("Cycle 2, 20 minutes in · learning");
  });

  it("writes a window exactly", () => {
    expect(windowLabel(86_400)).toBe("24 hours");
    expect(windowLabel(7 * 86_400)).toBe("7 days");
    expect(windowLabel(3_600)).toBe("1 hour");
    expect(windowLabel(90)).toBe("90 seconds");
  });
});

const DRAFT = {
  fallback: "b",
  options: [
    { key: "a", name: "Pay in one tap" },
    { key: "b", name: "Fewer returns" },
    { key: "c", name: "Ships today" },
  ],
  metric: { name: "checkout_completed", window_seconds: 86_400 },
} as Loop;
const draftResults = (draft: number) =>
  results({ cycle: null, share: null, lift: null, calls: { live: 0, draft, paused: 0 } });

describe("a draft", () => {
  it("reads its calls, its fallback and how much is ready", () => {
    expect(loopFacts("draft", DRAFT, { cycle: draftResults(1214), day: undefined }, NOW)).toEqual({
      calls: "1,214",
      serving: "Fewer returns",
      ready: "3 of 3",
    });
  });

  it("isn't ready until select calls arrive, and shows what to do", () => {
    const { checks, done, required } = readiness(DRAFT, draftResults(0));
    expect([done, required]).toEqual([2, 3]);
    expect(checks[2]).toMatchObject({ label: "select calls arriving", done: false });
    expect(checks[2].detail).toContain("Wire it");
  });

  it("names its options and its metric's window", () => {
    const { checks } = readiness(DRAFT, draftResults(214));
    expect(checks[0]).toEqual({ label: "Three options", detail: "Pay in one tap, Fewer returns, Ships today", done: true });
    expect(checks[1].detail).toBe("checkout_completed, window 24 hours");
    expect(checks[2].detail).toBe("214 in the last hour · all answered with the fallback");
  });

  it("never counts the optional webhook", () => {
    const { checks, required } = readiness(DRAFT, draftResults(214));
    expect(checks.filter((check) => check.optional).map((check) => check.label)).toEqual(["Alerts webhook"]);
    expect(required).toBe(3);
  });

  it("counts one option as not ready", () => {
    const [check] = readiness({ ...DRAFT, options: DRAFT.options.slice(0, 1) }, draftResults(1)).checks;
    expect(check).toMatchObject({ label: "One option", done: false });
  });

  it("falls back to the key when no option matches", () => {
    expect(fallbackName({ fallback: "gone", options: [] })).toBe("gone");
  });

  it("says each option's starting share by how many there are", () => {
    const body = (count: number) => launchConsequence({ options: Array(count).fill(DRAFT.options[0]) }).body;
    expect(body(2)).toContain("near half");
    expect(body(3)).toContain("near a third");
    expect(body(5)).toContain("near an even share");
  });
});
