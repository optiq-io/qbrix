export type Pulse = "live" | "paused" | "idle" | "empty";

export type Caption = string | { one: string; many: string };

export type FactRow = { key: string; label: string; caption?: Caption };

export type EyebrowPart = { text: string } | { counter: string; unit?: Caption };

export type StatusRow = {
  phrase: string;
  /** a "none yet" row: its hint stands in for the item and the facts */
  hint?: string;
  eyebrow: EyebrowPart[][];
  facts: FactRow[];
  /** "{name}" is the only thing filled in */
  prompts: string[];
  pulse: Pulse;
  /** the subject when the page doesn't name one: "Your workspace" */
  name?: string;
  /** this status is itself what the alert says, so it keeps its own phrase */
  ownsAlert?: boolean;
};

export type LoopStatus = "draft" | "warming_up" | "live" | "paused" | "retired";

export type StatusSubject =
  | { kind: "loop"; status: LoopStatus; alert?: boolean; asks?: boolean }
  | { kind: "workspace"; loops: number; alerts: number; asks: number }
  | { kind: "metrics"; count: number; alerts: number }
  | { kind: "metric"; arriving: boolean; alert?: boolean };

export type EyebrowToken = { kind: "text"; text: string } | { kind: "counter"; value: string };

const NEEDS_A_LOOK = "needs a look.";
const WAITING_ON_YOU = "is waiting on you.";

const LOOPS: Caption = { one: "loop", many: "loops" };
const DECISIONS_A_SECOND: Caption = { one: " decision a second", many: " decisions a second" };
const LEARNED: EyebrowPart[] = [{ text: "learned " }, { counter: "learned" }];

const LOOP: Record<LoopStatus, StatusRow> = {
  draft: {
    phrase: "is a draft.",
    eyebrow: [[{ counter: "calls", unit: { one: " call an hour", many: " calls an hour" } }], [{ text: "not learning" }]],
    facts: [
      { key: "calls", label: "Calls, last hour", caption: "answered with the fallback" },
      { key: "serving", label: "Serving", caption: "the fallback" },
      { key: "ready", label: "Ready", caption: "required" },
    ],
    prompts: ["Check my wiring for {name}", "What will launching {name} change?", "Draft a launch note for the team"],
    pulse: "idle",
  },
  warming_up: {
    phrase: "is warming up.",
    eyebrow: [[{ counter: "rate", unit: DECISIONS_A_SECOND }], LEARNED],
    facts: [
      { key: "ahead", label: "Ahead", caption: "option" },
      { key: "decisions", label: "Decisions", caption: "since launch" },
      { key: "outcomes", label: "Outcomes", caption: "since launch" },
      { key: "firstSeal", label: "First seal", caption: "when the first window closes" },
    ],
    prompts: ["Is every call reaching qbrix?", "When does the first outcome seal?", "What will change when it does?"],
    pulse: "live",
  },
  live: {
    phrase: "is live and learning.",
    eyebrow: [[{ counter: "rate", unit: DECISIONS_A_SECOND }], LEARNED],
    facts: [
      { key: "ahead", label: "Ahead", caption: "option" },
      { key: "share", label: "Share", caption: "of decisions, last 24 h" },
      { key: "lift", label: "Lift", caption: "vs an even split" },
      { key: "waiting", label: "Waiting", caption: "decisions to seal" },
    ],
    prompts: [
      "Which option in {name} is losing share, and why?",
      "What changed on {name} this week, and why?",
      "Should any option in {name} be retired?",
    ],
    pulse: "live",
  },
  paused: {
    phrase: "is paused.",
    eyebrow: [[{ text: "answering with the default" }], LEARNED],
    facts: [
      { key: "serving", label: "Serving", caption: "the default" },
      { key: "pausedFor", label: "Paused for" },
      { key: "failingNow", label: "Failing now", caption: "of calls, last 10 minutes" },
    ],
    prompts: [
      "Why did the decisions in {name} fail?",
      "Which merges landed around the pause?",
      "Write a note for the team about the pause",
    ],
    pulse: "paused",
    ownsAlert: true,
  },
  retired: {
    phrase: "has retired.",
    eyebrow: [[{ text: "read-only" }], [{ text: "retired " }, { counter: "retired" }]],
    facts: [
      { key: "lastAhead", label: "Last ahead", caption: "option" },
      { key: "decisions", label: "Decisions", caption: "in total" },
      { key: "ranFor", label: "Ran for", caption: "launch to retirement" },
    ],
    prompts: ["What did {name} learn before it retired?", "Why was {name} retired?"],
    pulse: "idle",
  },
};

const WORKSPACE_EYEBROW: EyebrowPart[][] = [
  [{ counter: "loops", unit: { one: " loop", many: " loops" } }],
  [{ counter: "rate", unit: DECISIONS_A_SECOND }],
];

const WORKSPACE_ACTIVE = {
  name: "Your workspace",
  eyebrow: WORKSPACE_EYEBROW,
  facts: [
    { key: "learning", label: "Learning", caption: LOOPS },
    { key: "warmingUp", label: "Warming up", caption: LOOPS },
    { key: "paused", label: "Paused", caption: LOOPS },
    { key: "drafts", label: "Drafts", caption: LOOPS },
  ],
  prompts: ["Which loop needs a look, and why?", "Summarise this week for the team", "Which loop should we look at next?"],
  pulse: "live",
} satisfies Omit<StatusRow, "phrase">;

const WORKSPACE_NONE: StatusRow = {
  name: "Your workspace",
  phrase: "has no loops yet.",
  hint: "A loop decides one thing in your product, like a headline or a ranking, and learns which option works from what your users do next.",
  eyebrow: WORKSPACE_EYEBROW,
  facts: [],
  prompts: ["Start a loop for the checkout headline"],
  pulse: "empty",
};

const METRICS_ACTIVE = {
  name: "Your metrics",
  eyebrow: [
    [{ counter: "count", unit: { one: " metric", many: " metrics" } }],
    [{ text: "updated " }, { counter: "updated" }],
  ],
  facts: [
    { key: "arriving", label: "Arriving", caption: { one: "metric", many: "metrics" } },
    { key: "outcomes", label: "Outcomes", caption: "a minute" },
    { key: "learnedFrom", label: "Learned from", caption: "of outcomes, last 7 days" },
  ],
  prompts: ["Which metric needs a look, and why?", "Create an order value metric, 7 days"],
  pulse: "live",
} satisfies Omit<StatusRow, "phrase">;

const METRICS_NONE: StatusRow = {
  name: "Your workspace",
  phrase: "has no metrics yet.",
  hint: "A metric is what your code sends when something good happens, such as a completed checkout. Loops in the workspace share it, and each decision waits its window for an outcome.",
  eyebrow: [
    [{ counter: "count", unit: { one: " metric", many: " metrics" } }],
    [{ counter: "rate", unit: { one: " outcome a second", many: " outcomes a second" } }],
  ],
  facts: [],
  prompts: ["Create an order value metric, 7 days"],
  pulse: "empty",
};

const METRIC_EYEBROW: EyebrowPart[][] = [
  [{ counter: "rate", unit: { one: " outcome a minute", many: " outcomes a minute" } }],
  [{ text: "version " }, { counter: "version" }],
];

const METRIC_ARRIVING = {
  eyebrow: METRIC_EYEBROW,
  facts: [
    { key: "window", label: "Window" },
    { key: "halfArrive", label: "Half arrive", caption: "after the decision" },
    { key: "mostArrive", label: "99% arrive", caption: "after the decision" },
    { key: "learnedFrom", label: "Learned from", caption: "of outcomes, last 7 days" },
  ],
  prompts: ["Is the window on {name} long enough?", "Which loops could share {name}?"],
  pulse: "live",
} satisfies Omit<StatusRow, "phrase">;

const METRIC_NONE: StatusRow = {
  phrase: "has no outcomes yet.",
  hint: "The first appears here the moment your code sends it.",
  eyebrow: METRIC_EYEBROW,
  facts: [],
  prompts: ["Check that my code sends {name}"],
  pulse: "empty",
};

export function statusRow(subject: StatusSubject): StatusRow {
  switch (subject.kind) {
    case "loop":
      return prioritised(LOOP[subject.status], subject.alert, subject.asks);
    case "workspace":
      if (subject.loops === 0 && !subject.alerts && !subject.asks) return WORKSPACE_NONE;
      return prioritised({ ...WORKSPACE_ACTIVE, phrase: "is learning." }, subject.alerts > 0, subject.asks > 0);
    case "metrics":
      if (subject.alerts > 0) return { ...METRICS_ACTIVE, phrase: "need a look." };
      return subject.count > 0 ? { ...METRICS_ACTIVE, phrase: "are arriving." } : METRICS_NONE;
    case "metric":
      if (subject.alert) return { ...METRIC_ARRIVING, phrase: NEEDS_A_LOOK };
      return subject.arriving ? { ...METRIC_ARRIVING, phrase: "is arriving." } : METRIC_NONE;
  }
}

function prioritised(row: StatusRow, alert?: boolean, asks?: boolean): StatusRow {
  if (alert) return row.ownsAlert ? row : { ...row, phrase: NEEDS_A_LOOK };
  return asks ? { ...row, phrase: WAITING_ON_YOU } : row;
}

export function captionFor(caption: Caption, value: string): string {
  if (typeof caption === "string") return caption;
  return value === "1" ? caption.one : caption.many;
}

/** a missing counter shows a dash, like a missing fact */
export function eyebrow(row: Pick<StatusRow, "eyebrow">, counters: Record<string, string | undefined>): EyebrowToken[][] {
  return row.eyebrow.map((segment) =>
    segment.flatMap((part): EyebrowToken[] => {
      if ("text" in part) return [{ kind: "text", text: part.text }];
      const value = counters[part.counter] ?? "—";
      const counter: EyebrowToken = { kind: "counter", value };
      return part.unit ? [counter, { kind: "text", text: captionFor(part.unit, value) }] : [counter];
    }),
  );
}

/** what the eyebrow reads while the server isn't answering: when it stopped, and the first figure as it was */
export function frozenEyebrow(segments: EyebrowToken[][], at: string): EyebrowToken[][] {
  const figure = segments.find((segment) => segment[0]?.kind === "counter");
  const frozen: EyebrowToken[][] = [[{ kind: "text", text: `frozen as of ${at}` }]];
  return figure ? [...frozen, [...figure, { kind: "text", text: " then" }]] : frozen;
}

export function prompts(row: Pick<StatusRow, "prompts">, name: string): string[] {
  return row.prompts.map((prompt) => prompt.replaceAll("{name}", name));
}
