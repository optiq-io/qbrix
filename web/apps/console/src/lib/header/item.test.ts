import { describe, expect, it } from "vitest";
import { leaderChanged, paused } from "./fixture";
import { advance, counter, ENTRANCE_MS, initialItem, itemMeta, pickItem, step, type ItemState } from "./item";
import type { HeaderEvent } from "./token";

const NOW = new Date(2026, 9, 30, 9, 41).getTime();
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const ids = (events: HeaderEvent[]) => events.map((event) => event.id);

describe("pickItem", () => {
  it("pins the oldest unresolved alert ahead of newer events, and counts it", () => {
    const picked = pickItem(
      [leaderChanged("newest", NOW - MINUTE), paused("later-alert", NOW - HOUR), paused("oldest-alert", NOW - 2 * HOUR), leaderChanged("older", NOW - DAY)],
      NOW,
    );
    expect(ids(picked.set)).toEqual(["oldest-alert", "later-alert", "newest", "older"]);
    expect(picked.pinned).toBe(true);
    expect(counter(picked, "oldest-alert")).toBe("1 of 4 this week");
  });

  it("keeps an alert older than a week, and leaves out resolved ones as alerts", () => {
    const picked = pickItem([paused("old", NOW - 30 * DAY), leaderChanged("recent", NOW - DAY)], NOW);
    expect(ids(picked.set)).toEqual(["old", "recent"]);
    expect(pickItem([paused("gone", NOW - DAY, false)], NOW).pinned).toBe(false);
  });

  it("shows the newest of the week without an alert, dropping what is older", () => {
    const picked = pickItem([leaderChanged("older", NOW - 8 * DAY), leaderChanged("newer", NOW - DAY), leaderChanged("newest", NOW - HOUR)], NOW);
    expect(ids(picked.set)).toEqual(["newest", "newer"]);
    expect(counter(picked, "newer")).toBe("2 of 2 this week");
  });

  it("falls back to the newest of all, without saying this week", () => {
    const picked = pickItem([leaderChanged("older", NOW - 30 * DAY), leaderChanged("newer", NOW - 9 * DAY)], NOW);
    expect(ids(picked.set)).toEqual(["newer", "older"]);
    expect(counter(picked, "newer")).toBe("1 of 2");
  });

  it("has nothing to show with no events", () => {
    const picked = pickItem([], NOW);
    expect(picked.set).toEqual([]);
    expect(initialItem(picked).shownId).toBeNull();
    expect(counter(picked, null)).toBeNull();
  });

  it("gives every viewer the same item for the same events", () => {
    const events = [leaderChanged("a", NOW - HOUR), leaderChanged("b", NOW - 2 * HOUR), paused("c", NOW - DAY)];
    expect(ids(pickItem(events, NOW).set)).toEqual(ids(pickItem([...events].reverse(), NOW).set));
  });
});

describe("advance", () => {
  /** plays arrivals in order and counts entrances, as the header does */
  function play(arrivals: [at: number, id: string][], until: number) {
    const events: HeaderEvent[] = [];
    let state: ItemState = initialItem(pickItem(events, NOW));
    let entrances = 0;
    const look = (at: number) => {
      const result = advance(state, pickItem(events, at), at);
      state = result.state;
      if (result.entered) entrances += 1;
      return result;
    };
    let dueAt: number | null = null;
    for (const [at, id] of arrivals) {
      if (dueAt !== null && dueAt <= at) look(dueAt);
      events.push(leaderChanged(id, at));
      dueAt = look(at).dueAt;
    }
    if (dueAt !== null && dueAt <= until) look(dueAt);
    return { state, entrances, picked: pickItem(events, until) };
  }

  it("lets five events within 10 s make one entrance, while the counter shows all five", () => {
    const { state, entrances, picked } = play(
      [
        [NOW, "1"],
        [NOW + 2000, "2"],
        [NOW + 4000, "3"],
        [NOW + 6000, "4"],
        [NOW + 8000, "5"],
      ],
      NOW + ENTRANCE_MS - 1,
    );
    expect(entrances).toBe(1);
    expect(state.shownId).toBe("1");
    expect(counter(picked, state.shownId)).toBe("5 of 5 this week");
  });

  it("shows the newest on the next turn", () => {
    const { state, entrances, picked } = play(
      [
        [NOW, "1"],
        [NOW + 2000, "2"],
        [NOW + 8000, "5"],
      ],
      NOW + ENTRANCE_MS,
    );
    expect(entrances).toBe(2);
    expect(state.shownId).toBe("5");
    expect(counter(picked, state.shownId)).toBe("1 of 3 this week");
  });

  it("says when to look again, and makes no entrance on load", () => {
    const events = [leaderChanged("first", NOW - HOUR)];
    const state = { ...initialItem(pickItem(events, NOW)), enteredAt: NOW };
    expect(state.shownId).toBe("first");

    const result = advance(state, pickItem([...events, leaderChanged("next", NOW + 1000)], NOW + 1000), NOW + 1000);
    expect(result).toEqual({ state, entered: false, dueAt: NOW + ENTRANCE_MS });

    const settled = advance(initialItem(pickItem(events, NOW)), pickItem(events, NOW), NOW);
    expect(settled.entered).toBe(false);
    expect(settled.dueAt).toBeNull();
  });

  it("returns the same state when nothing changed", () => {
    const picked = pickItem([leaderChanged("only", NOW)], NOW);
    const state = initialItem(picked);
    expect(advance(state, picked, NOW).state).toBe(state);
  });

  it("never displaces a pinned item with one that isn't", () => {
    const alert = paused("alert", NOW - HOUR);
    const state = initialItem(pickItem([alert], NOW));
    const later = NOW + 60_000;
    const result = advance(state, pickItem([alert, leaderChanged("newer", later)], later), later);
    expect(result.state.shownId).toBe("alert");
    expect(result.entered).toBe(false);
  });

  it("lets an alert enter over an ordinary item", () => {
    const first = leaderChanged("first", NOW - HOUR);
    const state = initialItem(pickItem([first], NOW));
    const result = advance(state, pickItem([first, paused("alert", NOW)], NOW), NOW);
    expect(result.state.shownId).toBe("alert");
    expect(result.entered).toBe(true);
  });

  it("moves on when the shown alert resolves", () => {
    const alert = paused("alert", NOW - DAY);
    const newer = leaderChanged("newer", NOW - HOUR);
    const state = initialItem(pickItem([alert, newer], NOW));
    expect(state.shownId).toBe("alert");

    const result = advance(state, pickItem([{ ...alert, alert: false }, newer], NOW), NOW);
    expect(result.state.shownId).toBe("newer");
    expect(result.entered).toBe(true);
  });

  it("removes the row when the last event goes", () => {
    const only = leaderChanged("only", NOW);
    const state = initialItem(pickItem([only], NOW));
    const result = advance(state, pickItem([], NOW), NOW);
    expect(result.state.shownId).toBeNull();
    expect(result.entered).toBe(false);
  });
});

describe("step", () => {
  const events = [paused("alert", NOW - DAY), leaderChanged("two", NOW - HOUR), leaderChanged("three", NOW - 2 * HOUR)];
  const picked = pickItem(events, NOW);

  it("steps through in order and wraps, without playing on its own", () => {
    let state = initialItem(picked);
    state = step(state, picked, 1);
    expect(state).toMatchObject({ shownId: "two", stepped: true });
    expect(counter(picked, state.shownId)).toBe("2 of 3 this week");
    state = step(step(state, picked, 1), picked, 1);
    expect(state).toMatchObject({ shownId: "alert", stepped: false });
    expect(step(state, picked, -1).shownId).toBe("three");
  });

  it("holds a stepped position when something arrives", () => {
    const state = step(initialItem(picked), picked, 1);
    const later = NOW + 60_000;
    const grown = pickItem([...events, leaderChanged("new", later)], later);
    const result = advance(state, grown, later);
    expect(result.state.shownId).toBe("two");
    expect(result.dueAt).toBeNull();
    expect(counter(grown, "two")).toBe("3 of 4 this week");
  });

  it("does nothing with one item", () => {
    const one = pickItem([leaderChanged("only", NOW)], NOW);
    const state = initialItem(one);
    expect(step(state, one, 1)).toBe(state);
  });
});

describe("itemMeta", () => {
  it("gives an alert its clock time and its context", () => {
    expect(itemMeta(paused("alert", new Date(2026, 9, 30, 3, 12).getTime()), NOW)).toEqual(["qbrix", "03:12", "decision errors"]);
  });

  it("dates an alert from an earlier day", () => {
    expect(itemMeta(paused("alert", new Date(2026, 9, 3, 3, 12).getTime()), NOW)[1]).toBe("3 Oct");
  });

  it.each([
    [20_000, "just now"],
    [MINUTE, "1 minute ago"],
    [47 * MINUTE, "47 minutes ago"],
    [HOUR, "1 hour ago"],
    [2 * DAY, "2 days ago"],
  ])("gives an event %d ms old a relative time", (age, label) => {
    expect(itemMeta(leaderChanged("event", NOW - age), NOW)).toEqual(["qbrix", label]);
  });

  it("dates an event older than a week", () => {
    expect(itemMeta(leaderChanged("event", new Date(2026, 9, 3, 12).getTime()), NOW)[1]).toBe("3 Oct");
  });

  it("gives a fold its range", () => {
    const fold = { ...leaderChanged("fold", new Date(2026, 9, 30, 14, 9).getTime()), firstAt: new Date(2026, 9, 30, 14, 2).getTime() };
    expect(itemMeta(fold, NOW)[1]).toBe("14:02 to 14:09");
  });
});
