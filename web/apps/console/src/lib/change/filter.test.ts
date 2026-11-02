import { describe, expect, it } from "vitest";
import { NO_FILTERS, filterParams, hasFilters, noneMatch, parseFilters } from "./filter";

describe("parseFilters", () => {
  it("reads every filter from the address and ignores the selected change", () => {
    const params = new URLSearchParams("who=connection&kind=loop.rename&loop=cta&metric=m&undoable=true&change=abc");
    expect(parseFilters(params)).toEqual({
      who: "connection",
      kind: "loop.rename",
      loop: "cta",
      metric: "m",
      undoable: true,
    });
  });

  it("drops a who the API doesn't know", () => {
    expect(parseFilters(new URLSearchParams("who=robots")).who).toBeNull();
  });
});

describe("filterParams", () => {
  it("round-trips through the address", () => {
    const filters = { ...NO_FILTERS, who: "qbrix" as const, undoable: true };
    expect(parseFilters(filterParams(filters))).toEqual(filters);
  });

  it("writes nothing with no filters", () => {
    expect(filterParams(NO_FILTERS).toString()).toBe("");
    expect(hasFilters(NO_FILTERS)).toBe(false);
  });
});

describe("noneMatch", () => {
  it("gives each filter its own line", () => {
    expect(noneMatch({ ...NO_FILTERS, who: "connection" })).toBe("No changes by agents.");
    expect(noneMatch({ ...NO_FILTERS, kind: "loop.pause" })).toBe("No loop.pause changes.");
    expect(noneMatch({ ...NO_FILTERS, loop: "cta" })).toBe("No changes to cta.");
    expect(noneMatch({ ...NO_FILTERS, undoable: true })).toBe("Nothing here can be undone.");
  });

  it("doesn't compose a line for several", () => {
    expect(noneMatch({ ...NO_FILTERS, who: "qbrix", undoable: true })).toBe("No changes match these filters.");
  });
});
