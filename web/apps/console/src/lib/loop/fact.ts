import { addDays, format, isSameDay } from "date-fns";
import type { Signal } from "@qbrix/ui/next/health";
import type { Loop, LoopCycle, LoopResults, ResultsRange } from "@/lib/api/types";
import type { FactValue } from "@/lib/header/fact";
import type { LoopStatus } from "@/lib/header/status";

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const ERRORS_NEED_A_LOOK = 0.01;
const MIN_OPTIONS = 2;

const COUNT_WORD: Record<number, string> = {
  1: "One",
  2: "Two",
  3: "Three",
  4: "Four",
  5: "Five",
  6: "Six",
  7: "Seven",
  8: "Eight",
  9: "Nine",
  10: "Ten",
};

const EVEN_SHARE: Record<number, string> = { 2: "near half", 3: "near a third" };

export const DRAFT_SIGNALS: Signal[] = [
  { label: "Decision errors", value: "none" },
  { label: "Outcomes arriving", value: "—" },
  { label: "Outcomes learned", value: "after launch" },
  { label: "Waiting to seal", value: "—" },
];

const STEP_WORD: Record<number, string> = {
  [MINUTE]: "minute",
  [5 * MINUTE]: "5 minutes",
  [15 * MINUTE]: "15 minutes",
  [30 * MINUTE]: "30 minutes",
  [HOUR]: "hour",
  [3 * HOUR]: "3 hours",
  [6 * HOUR]: "6 hours",
  [12 * HOUR]: "12 hours",
  [DAY]: "day",
};

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"}`;
}

/** the largest unit that fits: "40 seconds", "20 minutes", "3 hours", "12 days" */
function span(seconds: number): string {
  if (seconds < MINUTE) return plural(Math.max(0, Math.floor(seconds)), "second");
  if (seconds < HOUR) return plural(Math.floor(seconds / MINUTE), "minute");
  if (seconds < DAY) return plural(Math.floor(seconds / HOUR), "hour");
  return plural(Math.floor(seconds / DAY), "day");
}

function ago(at: string | null, now: number): string | undefined {
  return at ? `${span((now - Date.parse(at)) / 1000)} ago` : undefined;
}

function percent(share: number): string {
  return `${Math.round(share * 100)}%`;
}

function preciseRate(rate: number): string {
  if (rate === 0) return "0%";
  const digits = rate < 0.1 ? 2 : 1;
  return `${(rate * 100).toFixed(digits)}%`;
}

function cycleAgeSec(cycle: LoopCycle | null, now: number): number {
  return cycle?.started_at ? Math.max(1, (now - Date.parse(cycle.started_at)) / 1000) : 0;
}

function rate(perSecond: number): string {
  return perSecond < 10 ? perSecond.toFixed(1).replace(/\.0$/, "") : Math.round(perSecond).toLocaleString("en");
}

export function loopCounters(results: LoopResults, now: number): Record<string, string | undefined> {
  return {
    rate: rate(results.decisions_per_second),
    learned: ago(results.health.last_learned_at, now),
    calls: results.calls.draft.toLocaleString("en"),
  };
}

function sum(results: LoopResults | undefined, field: "decisions" | "waiting"): number {
  return results?.share?.options.reduce((total, option) => total + option[field], 0) ?? 0;
}

/** the option with the largest share of the last 24 hours, until leader events name it */
function ahead(day: LoopResults | undefined) {
  const shared = day?.share?.options.filter((option) => option.share !== null) ?? [];
  return shared.reduce<(typeof shared)[number] | undefined>(
    (best, option) => (!best || (option.share ?? 0) > (best.share ?? 0) ? option : best),
    undefined,
  );
}

function lift(results: LoopResults | undefined): FactValue | undefined {
  const value = results?.lift?.value;
  if (value === null || value === undefined) return undefined;
  const pct = Math.abs(value * 100).toFixed(1);
  const signed = `${value < 0 ? "−" : "+"}${pct}%`;
  return results?.lift?.early ? { value: signed, caption: "early · vs an even split" } : signed;
}

/** a metric's window as drawn: exact, and in hours up to a day */
export function windowLabel(seconds: number): string {
  if (seconds > DAY && seconds % DAY === 0) return plural(seconds / DAY, "day");
  if (seconds % HOUR === 0) return plural(seconds / HOUR, "hour");
  if (seconds % MINUTE === 0) return plural(seconds / MINUTE, "minute");
  return plural(seconds, "second");
}

function sealTime(at: number, now: number): string {
  if (at <= now) return "now";
  if (isSameDay(at, now)) return format(at, "HH:mm");
  if (isSameDay(at, addDays(now, 1))) return `tomorrow ${format(at, "HH:mm")}`;
  return format(at, "d MMM HH:mm");
}

/** when the earliest decision made so far seals */
export function firstSeal(cycle: LoopResults | undefined, windowSeconds: number, now: number): FactValue {
  const first = cycle?.share?.series.find((point) => point.decisions.some((count) => count > 0));
  if (!first) {
    return { value: "—", caption: `${windowLabel(windowSeconds)} after the first decision` };
  }
  const started = cycle?.cycle?.started_at ? Date.parse(cycle.cycle.started_at) : 0;
  return sealTime(Math.max(started, Date.parse(first.at)) + windowSeconds * 1000, now);
}

export function fallbackName(loop: Pick<Loop, "fallback" | "options">): string {
  return loop.options.find((option) => option.key === loop.fallback)?.name ?? loop.fallback;
}

export type ReadyCheck = { label: string; detail: string; done: boolean; optional?: boolean };

export type Readiness = { checks: ReadyCheck[]; done: number; required: number };

function optionCount(count: number): string {
  const word = COUNT_WORD[count] ?? String(count);
  return `${word} ${count === 1 ? "option" : "options"}`;
}

/** what a draft has so far. it informs and gates nothing: launching is always possible */
export function readiness(loop: Loop, results: LoopResults | undefined): Readiness {
  const calls = results?.calls.draft ?? 0;
  const required: ReadyCheck[] = [
    {
      label: optionCount(loop.options.length),
      detail: loop.options.map((option) => option.name).join(", "),
      done: loop.options.length >= MIN_OPTIONS,
    },
    {
      label: "A metric",
      detail: `${loop.metric.name}, window ${windowLabel(loop.metric.window_seconds)}`,
      done: true,
    },
    {
      label: "select calls arriving",
      detail: calls
        ? `${calls.toLocaleString("en")} in the last hour · all answered with the fallback`
        : "none in the last hour · the calls are under Wire it",
      done: calls > 0,
    },
  ];
  return {
    checks: [
      ...required,
      {
        label: "Alerts webhook",
        detail: "optional · not set up · alerts only reach the console without it",
        done: false,
        optional: true,
      },
    ],
    done: required.filter((check) => check.done).length,
    required: required.length,
  };
}

export function launchConsequence(loop: Pick<Loop, "options">): { title: string; body: string } {
  const share = EVEN_SHARE[loop.options.length] ?? "near an even share";
  return {
    title: "Launching starts cycle 1 for everyone.",
    body: `Each option starts ${share} of decisions and moves as qbrix learns. A launched loop can't go back to a draft.`,
  };
}

export function loopFacts(
  status: LoopStatus,
  loop: Loop,
  { cycle, day }: { cycle: LoopResults | undefined; day: LoopResults | undefined },
  now: number,
): Record<string, FactValue | undefined> {
  if (status === "draft") {
    const { done, required } = readiness(loop, cycle);
    return {
      calls: cycle?.calls.draft.toLocaleString("en"),
      serving: fallbackName(loop),
      ready: `${done} of ${required}`,
    };
  }
  if (status === "warming_up") {
    const outcomes = cycle?.health.outcomes.learned;
    return {
      decisions: sum(cycle, "decisions").toLocaleString("en"),
      outcomes: outcomes === undefined ? undefined : { value: outcomes.toLocaleString("en"), caption: "last hour" },
      firstSeal: firstSeal(cycle, loop.metric.window_seconds, now),
    };
  }
  const leader = ahead(day);
  return {
    ahead: leader?.name,
    share: leader?.share !== undefined && leader.share !== null ? percent(leader.share) : undefined,
    lift: lift(cycle),
    waiting: cycle ? sum(cycle, "waiting").toLocaleString("en") : undefined,
  };
}

export function healthSignals(results: LoopResults | undefined, now: number): Signal[] {
  if (!results) return [];
  const { decision_errors: errors, outcomes, last_outcome_at: lastOutcome } = results.health;
  const calls = results.calls.live + errors;
  const errorRate = calls ? errors / calls : 0;
  const arrived = outcomes.learned + outcomes.late + outcomes.duplicate + outcomes.earlier_cycle;
  return [
    {
      label: "Decision errors",
      value: preciseRate(errorRate),
      state: errorRate >= ERRORS_NEED_A_LOOK ? "part" : "ok",
    },
    { label: "Outcomes arriving", value: ago(lastOutcome, now) ?? "—", state: lastOutcome ? "ok" : undefined },
    {
      label: "Outcomes learned",
      value: arrived ? preciseRate(outcomes.learned / arrived) : "—",
      state: arrived ? "ok" : undefined,
    },
    { label: "Waiting to seal", value: sum(results, "waiting").toLocaleString("en") },
  ];
}

export function chartCaption(results: LoopResults, range: ResultsRange, firstRun: boolean): string | undefined {
  const { cycle, share } = results;
  if (!cycle?.started_at || !share) return undefined;
  const started = Date.parse(cycle.started_at);
  if (firstRun && range === "cycle") {
    const word = STEP_WORD[share.step_seconds] ?? "interval";
    return `cycle ${cycle.number} · by ${word} since ${format(started, "HH:mm")}`;
  }
  if (range === "24h") return `cycle ${cycle.number}, last 24 hours`;
  if (range === "7d") return `cycle ${cycle.number}, last 7 days`;
  return `cycle ${cycle.number}, ${format(started, "d MMM")} to now`;
}

export function nowLine(status: LoopStatus, cycle: LoopCycle, now: number): string {
  const age = cycleAgeSec(cycle, now);
  if (status === "warming_up") return `Cycle ${cycle.number}, ${span(age)} in · learning`;
  return `Day ${Math.floor(age / DAY) + 1} of cycle ${cycle.number} · learning`;
}
