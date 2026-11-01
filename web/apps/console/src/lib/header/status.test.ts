import { describe, expect, it } from "vitest";
import { facts } from "./fact";
import { fixture, FIXTURES } from "./fixture";
import { eyebrow, frozenEyebrow, prompts, statusRow, type EyebrowToken, type LoopStatus } from "./status";
import type { Token } from "./token";

const NOW = new Date(2026, 9, 30, 9, 41).getTime();

function read(tokens: EyebrowToken[][]) {
  return tokens.map((segment) => segment.map((t) => (t.kind === "text" ? t.text : t.value)).join("")).join(" · ");
}

function shown(key: string) {
  const { subject, counters, values } = fixture(key);
  const row = statusRow(subject);
  return {
    phrase: row.phrase,
    name: row.name,
    eyebrow: read(eyebrow(row, counters)),
    facts: facts(row, values).map(({ label, value, caption }) => [label, value, caption]),
  };
}

describe("the headers drawn in the band", () => {
  it("reads a live loop", () => {
    expect(shown("live")).toEqual({
      phrase: "is live and learning.",
      name: undefined,
      eyebrow: "38 decisions a second · learned 40 seconds ago",
      facts: [
        ["Ahead", "Pay in one tap", "option"],
        ["Share", "58%", "of decisions, last 24 h"],
        ["Lift", "+6.2%", "vs an even split"],
        ["Waiting", "214", "decisions to seal"],
      ],
    });
  });

  it("reads a loop warming up, with no leader", () => {
    expect(shown("warming-up")).toMatchObject({
      phrase: "is warming up.",
      eyebrow: "16 decisions a second · learned 12 seconds ago",
      facts: [
        ["Ahead", "—", "option"],
        ["Decisions", "1,920", "since launch"],
        ["Outcomes", "312", "since launch"],
        ["First seal", "tomorrow 14:00", "when the first window closes"],
      ],
    });
  });

  it("reads a draft", () => {
    expect(shown("draft")).toMatchObject({
      phrase: "is a draft.",
      eyebrow: "214 calls an hour · not learning",
      facts: [
        ["Calls, last hour", "214", "answered with the fallback"],
        ["Serving", "Fewer returns", "the fallback"],
        ["Ready", "4 of 4", "required"],
      ],
    });
  });

  it("reads a loop qbrix paused as paused, not as needing a look", () => {
    expect(shown("paused")).toMatchObject({
      phrase: "is paused.",
      eyebrow: "answering with the default · learned 4 minutes ago",
      facts: [
        ["Serving", "Relevance", "the default"],
        ["Paused for", "6 h 29 m", "since 03:12"],
        ["Answered", "214", "with the fallback, last hour"],
      ],
    });
  });

  it("reads a retired loop", () => {
    expect(shown("retired")).toMatchObject({ phrase: "has retired.", eyebrow: "read-only · retired 3 Oct" });
  });

  it("reads the workspace", () => {
    expect(shown("workspace-needs-a-look")).toMatchObject({
      name: "Your workspace",
      phrase: "needs a look.",
      eyebrow: "4 loops · 1,240 decisions a second",
      facts: [
        ["Learning", "3", "loops"],
        ["Warming up", "0", "loops"],
        ["Paused", "1", "loop"],
        ["Drafts", "0", "loops"],
      ],
    });
  });

  it("reads the metrics list and a metric", () => {
    expect(shown("metrics-arriving")).toMatchObject({
      name: "Your metrics",
      phrase: "are arriving.",
      eyebrow: "4 metrics · updated 10 seconds ago",
    });
    expect(shown("metric-arriving")).toMatchObject({
      phrase: "is arriving.",
      eyebrow: "38 outcomes a minute · version 3",
      facts: [
        ["Window", "24 hours", "conversion"],
        ["Half arrive", "40 min", "after the decision"],
        ["99% arrive", "11 h", "after the decision"],
        ["Learned from", "98.7%", "of outcomes, last 7 days"],
      ],
    });
  });
});

describe("status priority", () => {
  const STATUSES: LoopStatus[] = ["draft", "warming_up", "live", "retired"];

  it.each(STATUSES)("an alert outranks an ask on a %s loop, and both outrank its own phrase", (status) => {
    const own = statusRow({ kind: "loop", status });
    expect(statusRow({ kind: "loop", status, alert: true, asks: true }).phrase).toBe("needs a look.");
    expect(statusRow({ kind: "loop", status, asks: true }).phrase).toBe("is waiting on you.");
    expect(statusRow({ kind: "loop", status, alert: true }).facts).toEqual(own.facts);
  });

  it("keeps a paused loop's phrase under an alert, and lets an ask through without one", () => {
    expect(statusRow({ kind: "loop", status: "paused", alert: true, asks: true }).phrase).toBe("is paused.");
    expect(statusRow({ kind: "loop", status: "paused", asks: true }).phrase).toBe("is waiting on you.");
  });

  it("orders the workspace", () => {
    const at = (loops: number, alerts: number, asks: number) => statusRow({ kind: "workspace", loops, alerts, asks }).phrase;
    expect(at(4, 1, 1)).toBe("needs a look.");
    expect(at(4, 0, 1)).toBe("is waiting on you.");
    expect(at(4, 0, 0)).toBe("is learning.");
    expect(at(0, 0, 0)).toBe("has no loops yet.");
  });

  it("orders the metrics", () => {
    const at = (count: number, alerts: number) => statusRow({ kind: "metrics", count, alerts }).phrase;
    expect(at(4, 1)).toBe("need a look.");
    expect(at(4, 0)).toBe("are arriving.");
    expect(at(0, 0)).toBe("has no metrics yet.");
  });
});

describe("none yet", () => {
  it.each(["workspace-none", "metrics-none"])("%s has a hint and no facts", (key) => {
    const row = statusRow(fixture(key).subject);
    expect(row.hint).toBeTruthy();
    expect(facts(row, fixture(key).values)).toEqual([]);
  });

  it("names the workspace on the metrics list's empty page", () => {
    expect(statusRow({ kind: "metrics", count: 0, alerts: 0 }).name).toBe("Your workspace");
  });
});

describe("eyebrow, facts and prompts", () => {
  it("shows a dash for a missing counter or value", () => {
    const row = statusRow({ kind: "loop", status: "live" });
    expect(read(eyebrow(row, {}))).toBe("— decisions a second · learned —");
    expect(facts(row, {}).map((fact) => fact.value)).toEqual(["—", "—", "—", "—"]);
  });

  it("agrees a unit with a count of one", () => {
    const row = statusRow({ kind: "workspace", loops: 1, alerts: 0, asks: 0 });
    expect(read(eyebrow(row, { loops: "1", rate: "1" }))).toBe("1 loop · 1 decision a second");
  });

  it("freezes to the time and the first figure", () => {
    const live = eyebrow(statusRow({ kind: "loop", status: "live" }), { rate: "38", learned: "40 seconds ago" });
    expect(read(frozenEyebrow(live, "14:02"))).toBe("frozen as of 14:02 · 38 decisions a second then");
  });

  it("freezes to the time alone when nothing leads with a figure", () => {
    const row = eyebrow(statusRow({ kind: "loop", status: "paused" }), { learned: "4 minutes ago" });
    expect(read(frozenEyebrow(row, "14:02"))).toBe("frozen as of 14:02");
  });

  it("fills in only the name", () => {
    const row = statusRow({ kind: "loop", status: "draft" });
    expect(prompts(row, "checkout-headline")[0]).toBe("Check my wiring for checkout-headline");
    for (const prompt of prompts(row, "checkout-headline")) expect(prompt).not.toContain("{");
  });
});

function tokenText(token: Token): string {
  if (token.kind === "text") return token.text;
  if (token.kind === "actor") return token.actor.kind === "qbrix" ? "qbrix" : (token.actor.name ?? "GitHub");
  return token.name;
}

/** everything a header can put on screen, from every fixture */
function everyString(): string[] {
  return FIXTURES.flatMap(({ name, subject, counters, values, events }) => {
    const row = statusRow(subject);
    return [
      name ?? "",
      row.name ?? "",
      row.phrase,
      row.hint ?? "",
      read(eyebrow(row, counters)),
      ...facts(row, values).flatMap((fact) => [fact.label, fact.value, fact.caption ?? ""]),
      ...prompts(row, name ?? ""),
      ...events(NOW).flatMap((event) => [
        ...event.pieces.map(tokenText),
        event.source,
        event.context ?? "",
        ...(event.diff ?? []).flatMap((diff) => [diff.field, diff.before ?? "", diff.after ?? ""]),
      ]),
    ];
  });
}

describe("nothing is composed", () => {
  it("has no judgement word or claimed cause anywhere", () => {
    const banned = /\b(close|steady|because|due to)\b|\bsince (?:the |a )?(?:[A-Z]|change|edit)/i;
    const offending = everyString().filter((line) => banned.test(line) && !/^since (launch|\d)/.test(line));
    expect(offending).toEqual([]);
  });

  it("never puts markup in a string", () => {
    expect(everyString().filter((line) => /<[a-z/]/i.test(line))).toEqual([]);
  });

  it("gives every piece of every event a known kind", () => {
    const kinds = new Set(["text", "actor", "loop", "metric", "option"]);
    for (const { events } of FIXTURES) {
      for (const event of events(NOW)) {
        for (const piece of event.pieces) expect(kinds.has(piece.kind)).toBe(true);
      }
    }
  });
});
