import { describe, expect, it } from "vitest";
import { ApiError } from "../api/types";
import { asSentence, refusalOf } from "./refusal";

describe("refusalOf", () => {
  it("names the later change when something moved it", () => {
    const error = new ApiError(409, "a later change exists", "CHANGE_NOT_UNDOABLE", { later_change_id: "later" });
    expect(refusalOf(error)).toEqual({ kind: "moved", laterId: "later" });
  });

  it("carries the reason for any other refusal", () => {
    const error = new ApiError(409, "already undone", "CHANGE_NOT_UNDOABLE");
    expect(refusalOf(error)).toEqual({ kind: "refused", detail: "already undone" });
  });

  it("leaves every other failure to the toast", () => {
    expect(refusalOf(new ApiError(403, "no", "INSUFFICIENT_SCOPES"))).toBeNull();
    expect(refusalOf(new Error("network"))).toBeNull();
  });
});

describe("asSentence", () => {
  it("capitalises and closes the proxy's reason", () => {
    expect(asSentence("deleting a loop cannot be undone")).toBe("Deleting a loop cannot be undone.");
    expect(asSentence("Already a sentence.")).toBe("Already a sentence.");
  });
});
