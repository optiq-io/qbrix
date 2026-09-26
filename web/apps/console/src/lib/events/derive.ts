import type { Experiment, UnifiedEvent, User } from "@/lib/api/types";

// ClickHouse hands every `data` value back as a string — `arm_index: "1"`,
// `reward: "1"`, `is_default: "false"` — so anything numeric here is parsed,
// never used raw.

export type NameIndex = {
  experimentName: (id: string) => string | null;
  armName: (experimentId: string, armIndex: number) => string | null;
};

/** one `/v1/experiments` fetch resolves both columns: the list already carries
 *  `pool.arms` with index and name, so no per-row lookup is needed. */
export function buildNameIndex(experiments: Experiment[]): NameIndex {
  const byId = new Map<string, string>();
  const arms = new Map<string, string>();

  for (const exp of experiments) {
    byId.set(exp.id, exp.name);
    for (const arm of exp.pool?.arms ?? []) {
      arms.set(`${exp.id}:${arm.index}`, arm.name);
    }
  }

  return {
    experimentName: (id) => byId.get(id) ?? null,
    armName: (experimentId, armIndex) =>
      arms.get(`${experimentId}:${armIndex}`) ?? null,
  };
}

/** the variant a row is about.
 *
 *  selection events carry `arm_name` outright; **feedback events carry only
 *  `arm_index`**, so without the pool half this column would be blank. audit
 *  events are not about a variant at all. */
export function variantOf(event: UnifiedEvent, names: NameIndex): string | null {
  const direct = event.data?.arm_name;
  if (typeof direct === "string" && direct) return direct;

  const raw = event.data?.arm_index;
  if (raw === undefined || raw === null) return null;
  const index = Number(raw);
  if (!Number.isInteger(index)) return null;

  return names.armName(event.resource_id, index);
}

export type ResourceLabel = { text: string; resolved: boolean };

/** audit rows point at whatever the action touched — a pool, a gate, an
 *  experiment. printing a pool's name under a column headed EXPERIMENT would
 *  be a lie, so unresolved resources render as their type and id instead. */
export function resourceOf(
  event: UnifiedEvent,
  names: NameIndex,
): ResourceLabel {
  const name = names.experimentName(event.resource_id);
  if (name) return { text: name, resolved: true };

  const type = event.data?.resource_type;
  const id = event.resource_id ? event.resource_id.slice(0, 8) : "";
  if (typeof type === "string" && type) {
    return { text: id ? `${type} · ${id}` : type, resolved: false };
  }
  return { text: id || "—", resolved: false };
}

export type ActorLabel = { text: string; resolved: boolean };

/** `actor_id` is a user id, so the column is a uuid until the workspace roster
 *  resolves it. only audit rows carry one — a selection had no actor, it was a
 *  request, and printing "system" on those fills the busiest column on the page
 *  with a word that means nothing. */
export function actorOf(
  event: UnifiedEvent,
  actors: ActorIndex,
): ActorLabel | null {
  const raw = event.data?.actor_id;
  if (typeof raw !== "string" || !raw) return null;
  // cortex publishes its training-lifecycle audit under a literal, not an id
  if (raw === "system") return { text: "system", resolved: true };

  const name = actors.name(raw);
  return name ? { text: name, resolved: true } : { text: raw.slice(0, 8), resolved: false };
}

export type ActorIndex = { name: (id: string) => string | null };

/** one `/auth/workspace/members` fetch resolves the column; every role may read
 *  it. an actor who has since left the workspace stays a short id. */
export function buildActorIndex(users: User[]): ActorIndex {
  const byId = new Map<string, string>();
  for (const user of users) byId.set(user.id, user.name || user.email);
  return { name: (id) => byId.get(id) ?? null };
}

// rendered in their own columns, or too long to belong in a one-line readout
// (`request_id` is a ~200-char signed token)
const OMIT_FROM_PAYLOAD = new Set([
  "arm_name",
  "arm_index",
  "arm_id",
  "request_id",
  "resource_type",
]);

/** what is left of `data` once the dedicated columns have taken their share.
 *  `omit` adds to that set for a surface with more columns than the event log —
 *  the activity tab draws the actor, so it must not repeat it here. */
export function payloadOf(event: UnifiedEvent, omit?: Iterable<string>): string {
  const out: Record<string, unknown> = {};
  const skip = omit ? new Set([...OMIT_FROM_PAYLOAD, ...omit]) : OMIT_FROM_PAYLOAD;

  for (const [key, value] of Object.entries(event.data ?? {})) {
    if (skip.has(key)) continue;
    // audit nests its detail as a JSON *string*; flatten it so the column
    // shows the change rather than an escaped blob
    if (key === "payload" && typeof value === "string") {
      try {
        const parsed = JSON.parse(value);
        if (parsed && typeof parsed === "object") {
          Object.assign(out, parsed);
          continue;
        }
      } catch {
        // not json — fall through and keep it as-is
      }
    }
    out[key] = value;
  }

  return Object.keys(out).length === 0 ? "—" : JSON.stringify(out);
}

const STREAM_DOT: Record<string, string> = {
  feedback: "bg-viz-1",
  selection: "bg-viz-2",
  audit: "bg-text-faint",
};

export function streamDot(category: string): string {
  return STREAM_DOT[category] ?? "bg-text-faint";
}

/** a stable react key. the feed has no event id, and on the activity tab
 *  `resource_id` is the same experiment on every row, so the request id is the
 *  only thing separating two events in the same millisecond. */
export function eventKey(event: UnifiedEvent): string {
  const request = event.data?.request_id;
  const suffix = typeof request === "string" && request ? request : event.resource_id;
  return `${event.timestamp_ms}:${event.category}:${event.name}:${suffix}`;
}

/** `19:42:08.412` — the board's time column, to the millisecond. */
export function logTime(ms: number): string {
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}.${String(d.getMilliseconds()).padStart(3, "0")}`;
}
