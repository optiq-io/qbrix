import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const linked: { routes: string[]; pending: string[] } = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../../../../../svc/proxy/src/proxysvc/core/console_routes.json", import.meta.url)),
    "utf8",
  ),
);

const APP = fileURLToPath(new URL("../app", import.meta.url));

const isGroup = (segment: string) => segment.startsWith("(") && segment.endsWith(")");
const isCatchAll = (segment: string) => segment.startsWith("[...") || segment.startsWith("[[...");
const normalise = (segment: string) => (segment.startsWith("[") ? "[]" : segment);

function pages(dir: string, path: string[] = []): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isFile() && entry.name === "page.tsx") found.push(`/${path.join("/")}`);
    if (!entry.isDirectory() || isCatchAll(entry.name)) continue;
    const next = isGroup(entry.name) ? path : [...path, normalise(entry.name)];
    found.push(...pages(join(dir, entry.name), next));
  }
  return found;
}

const served = new Set(pages(APP));
const asServed = (route: string) => route.split("/").map(normalise).join("/");

describe("the console routes the proxy links to", () => {
  it.each(linked.routes)("%s has a page", (route) => {
    expect(served.has(asServed(route)), `${route} has no page under src/app`).toBe(true);
  });

  it.each(linked.pending)("%s is still pending", (route) => {
    expect(
      served.has(asServed(route)),
      `${route} has a page now: move it from pending to routes in console_routes.json`,
    ).toBe(false);
  });
});
