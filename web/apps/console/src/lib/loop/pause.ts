import { format, isSameDay } from "date-fns";
import type { Signal } from "@qbrix/ui/next/health";
import type { ChangeEntry, DecisionErrorEvidence, Loop, LoopResults } from "@/lib/api/types";
import type { FactValue } from "@/lib/header/fact";

const MINUTE = 60_000;
const RULE_MINUTES = 10;
const DECISION_ERRORS = "decision_errors";
const RULE = `over 5% of at least 100 calls, in ${RULE_MINUTES} minutes`;

export type Pause = {
  id: string;
  at: number;
  byQbrix: boolean;
  /** only a safety pause has any: a person's pause, from undoing a resume, doesn't */
  evidence: DecisionErrorEvidence | null;
};

export type PauseRow = { label: string; value: string };

function isDecisionErrors(evidence: ChangeEntry["evidence"]): evidence is DecisionErrorEvidence {
  return evidence?.signal === DECISION_ERRORS;
}

/** read from the changes, not the latest one: a loop can be renamed while paused */
export function pauseOf(loop: Pick<Loop, "state">, changes: ChangeEntry[]): Pause | null {
  if (loop.state !== "paused") return null;
  const entry = changes.find((change) => change.kind === "loop.pause");
  if (!entry?.at) return null;
  return {
    id: entry.id,
    at: Date.parse(entry.at),
    byQbrix: entry.pieces.find((piece) => piece.kind === "actor")?.actor?.kind === "qbrix",
    evidence: isDecisionErrors(entry.evidence) ? entry.evidence : null,
  };
}

function rate(evidence: DecisionErrorEvidence): string {
  return `${(evidence.rate * 100).toFixed(1)}%`;
}

function reasons(evidence: DecisionErrorEvidence): string[] {
  return Object.entries(evidence.reasons)
    .sort(([, a], [, b]) => b - a)
    .map(([reason, count]) => `${reason.replaceAll("_", " ")} ${count.toLocaleString("en")}`);
}

/** the window is shorter than the rule's when the loop went live just before the pause */
function shortWindow(evidence: DecisionErrorEvidence): string[] {
  const minutes = Math.ceil((Date.parse(evidence.window_end) - Date.parse(evidence.window_start)) / MINUTE);
  if (minutes >= RULE_MINUTES) return [];
  return [`over ${minutes} ${minutes === 1 ? "minute" : "minutes"}`];
}

function atPause(evidence: DecisionErrorEvidence): string {
  const counted = `${evidence.errors.toLocaleString("en")} of ${evidence.calls.toLocaleString("en")}`;
  return [rate(evidence), counted, ...reasons(evidence), ...shortWindow(evidence)].join(" · ");
}

function whilePaused(fallback: string, results: LoopResults | undefined): string {
  const answered = `answered with ${fallback}`;
  if (!results) return answered;
  const calls = results.calls.paused;
  return `${answered} · ${calls.toLocaleString("en")} ${calls === 1 ? "call" : "calls"}, last hour`;
}

export function pauseRows(pause: Pause | null, fallback: string, results: LoopResults | undefined): PauseRow[] {
  if (!pause?.evidence) return [];
  return [
    { label: "Signal", value: "decision errors" },
    { label: "Rule", value: RULE },
    { label: "At pause", value: atPause(pause.evidence) },
    { label: "While paused", value: whilePaused(fallback, results) },
  ];
}

function clock(at: number, now: number): string {
  return isSameDay(at, now) ? format(at, "HH:mm") : format(at, "d MMM HH:mm");
}

function duration(ms: number): string {
  const minutes = Math.max(0, Math.floor(ms / MINUTE));
  if (minutes < 60) return `${minutes} m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ${minutes % 60} m`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

export function pausedFor(pause: Pause, now: number): FactValue {
  return { value: duration(now - pause.at), caption: `since ${clock(pause.at, now)}` };
}

/** while paused nothing reaches the engine, so errors stop being counted: the last measure is the one at the pause */
export function pausedErrors(pause: Pause | null): Signal {
  if (!pause?.evidence) return { label: "Decision errors", value: "—" };
  return { label: "Decision errors", value: `${rate(pause.evidence)} at pause`, state: "part" };
}

export function resumeConsequence(
  cycle: number | undefined,
  pause: Pause | null,
  now: number,
): { title: string; body: string } {
  const before = pause ? clock(pause.at, now) : "the pause";
  return {
    title: cycle ? `Resuming continues cycle ${cycle} where it left off.` : "Resuming continues where it left off.",
    body: `Outcomes for decisions made before ${before} still count as they arrive. qbrix never resumes on its own.`,
  };
}
