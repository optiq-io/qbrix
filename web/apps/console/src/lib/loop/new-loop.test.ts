import { describe, expect, it } from "vitest";
import {
  createConsequence,
  fallbackNote,
  keyFrom,
  loopErrorField,
  loopKey,
  optionKeys,
  validateDraft,
  type LoopDraft,
  type OptionRow,
} from "./new-loop";

function row(id: string, name: string, overrides: Partial<OptionRow> = {}): OptionRow {
  return { id, name, key: null, config: "", ...overrides };
}

function draft(overrides: Partial<LoopDraft> = {}): LoopDraft {
  return {
    name: "Checkout headline",
    key: null,
    purpose: "  Finish checkout.  ",
    options: [row("a", "Pay in one tap"), row("b", "Fewer returns")],
    fallback: null,
    metric: "checkout_completed",
    ...overrides,
  };
}

describe("keys", () => {
  it("follows the server's slug", () => {
    expect(keyFrom("  Pay in one tap! ", "option")).toBe("pay-in-one-tap");
    expect(keyFrom("Başlık", "loop")).toBe("ba-l-k");
    expect(keyFrom("日本語", "loop")).toBe("loop");
    expect(keyFrom(`${"a".repeat(59)} b c`, "loop")).toBe("a".repeat(59));
  });

  it("has no loop key until there is a name, and steps around the reserved one", () => {
    expect(loopKey({ name: "  ", key: null })).toBe("");
    expect(loopKey({ name: "New", key: null })).toBe("new-2");
    expect(loopKey({ name: "New", key: "mine" })).toBe("mine");
  });

  it("reserves given option keys before generating the rest in order", () => {
    const keys = optionKeys([row("a", "Same"), row("b", "Same"), row("c", "Other", { key: "same" })]);
    expect([keys.get("a"), keys.get("b"), keys.get("c")]).toEqual(["same-2", "same-3", "same"]);
  });
});

describe("validateDraft", () => {
  it("builds the body, trimming text and sending the keys it shows", () => {
    const { body } = validateDraft(
      draft({ options: [row("a", "One", { config: '{ "headline": "x" }' }), row("b", "Two"), row("c", "")] }),
    );
    expect(body).toEqual({
      name: "Checkout headline",
      key: "checkout-headline",
      purpose: "Finish checkout.",
      metric: "checkout_completed",
      options: [
        { name: "One", key: "one", config: { headline: "x" } },
        { name: "Two", key: "two", config: {} },
      ],
      fallback: "one",
    });
  });

  it("sends the chosen fallback as its key", () => {
    expect(validateDraft(draft({ fallback: "b" })).body?.fallback).toBe("fewer-returns");
  });

  it.each(["[1]", "3", "null", '"text"', "{ broken"])("refuses %s as a config, on its row", (config) => {
    const { errors } = validateDraft(draft({ options: [row("a", "One", { config }), row("b", "Two")] }));
    expect(errors?.rows?.a?.config).toContain("JSON object");
    expect(errors?.rows?.b).toBeUndefined();
  });

  it("needs two filled options, on the options section", () => {
    const { errors } = validateDraft(draft({ options: [row("a", "One"), row("b", "")] }));
    expect(errors?.options).toBe("A loop needs at least two options.");
  });

  it("needs a name for a row that has anything else", () => {
    const { errors } = validateDraft(draft({ options: [row("a", "One"), row("b", "", { config: "{}" }), row("c", "Three")] }));
    expect(errors?.rows?.b?.name).toBe("Every option needs a name.");
  });

  it("refuses bad, duplicate and reserved keys", () => {
    expect(validateDraft(draft({ key: "Bad Key" })).errors?.key).toContain("lowercase");
    expect(validateDraft(draft({ key: "new" })).errors?.key).toContain("qbrix uses");
    const { errors } = validateDraft(draft({ options: [row("a", "One", { key: "x" }), row("b", "Two", { key: "x" })] }));
    expect(errors?.rows?.b?.key).toBe("Two options have this key.");
  });

  it("needs a name and a metric", () => {
    const { errors } = validateDraft(draft({ name: " ", metric: null }));
    expect(errors?.name).toBeDefined();
    expect(errors?.metric).toBeDefined();
  });
});

describe("what it says", () => {
  it("names the key and the fallback once they exist", () => {
    expect(createConsequence(draft())).toBe(
      "Creates checkout-headline as a draft. Your app gets the fallback, Pay in one tap, until you launch it.",
    );
    expect(createConsequence(draft({ name: "", options: [row("a", "")] }))).toBe(
      "Creates a draft. Your app gets the fallback until you launch it.",
    );
  });

  it("names a fallback other than the first option", () => {
    expect(fallbackNote(draft())).toMatch(/^The first option is the fallback/);
    expect(fallbackNote(draft({ fallback: "b" }))).toMatch(/^Fewer returns is the fallback/);
  });

  it("falls back to the first filled row when the chosen one is blank", () => {
    expect(fallbackNote(draft({ options: [row("a", "One"), row("b", "")], fallback: "b" }))).toMatch(/^The first option/);
  });
});

describe("loopErrorField", () => {
  it.each([
    ["LOOP_KEY_TAKEN", "a loop with the key 'x' already exists", "key"],
    ["INVALID_LOOP", "a loop key is what code calls: lowercase", "key"],
    ["INVALID_LOOP", "a loop can't have the key 'new': qbrix uses it", "key"],
    ["INVALID_LOOP", "no metric named or with id 'revenue'", "metric"],
    ["INVALID_LOOP", "a loop needs a metric: the one it improves", "metric"],
    ["INVALID_LOOP", "a loop needs a name", "name"],
    ["INVALID_LOOP", "a loop needs at least 2 options, got 1", "options"],
    ["INVALID_LOOP", "two options have the key 'a'", "options"],
    ["INVALID_LOOP", "the fallback 'x' is not one of the loop's options (a, b)", "options"],
  ])("%s %s goes on %s", (code, detail, field) => {
    expect(loopErrorField({ code, detail })?.field).toBe(field);
  });

  it("leaves what no field can fix to the toast", () => {
    expect(loopErrorField({ code: "INVALID_LOOP", detail: "unknown engine 'x'" })).toBeNull();
    expect(loopErrorField({ code: "INSUFFICIENT_SCOPES", detail: "insufficient permissions" })).toBeNull();
    expect(loopErrorField({ detail: "request failed" })).toBeNull();
  });
});
