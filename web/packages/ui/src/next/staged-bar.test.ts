import { describe, expect, it } from "vitest";
import { applyLabel } from "./staged-bar";

describe("applyLabel", () => {
  it("follows the count", () => {
    expect(applyLabel(1)).toBe("Apply");
    expect(applyLabel(2)).toBe("Apply both");
    expect(applyLabel(3)).toBe("Apply all 3");
  });
});
