#!/usr/bin/env node
//
// the console's edition boundary: `src/ee` and `src/app/(ee)` hold the cloud
// plugin, and exactly one core module — `src/lib/edition.ts` — may import from
// them. that is what keeps relocating the plugin a one-file change.
//
// the check resolves specifiers to paths rather than matching text, so a
// relative reach (`../ee/...`) is caught alongside an aliased one (`@/ee/...`).

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "..", "src");
const eeRoots = [join(src, "ee"), join(src, "app", "(ee)")];
const seam = join(src, "lib", "edition.ts");

function* sources(dir) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) yield* sources(path);
    else if (/\.tsx?$/.test(entry)) yield path;
  }
}

function specifiers(source) {
  const found = [];
  for (const re of [/\bfrom\s*["']([^"']+)["']/g, /\bimport\s*\(\s*["']([^"']+)["']/g]) {
    for (const match of source.matchAll(re)) found.push(match[1]);
  }
  return found;
}

function resolveSpecifier(specifier, file) {
  if (specifier.startsWith("@/")) return join(src, specifier.slice(2));
  if (specifier.startsWith(".")) return resolve(dirname(file), specifier);
  return null;
}

const violations = [];

for (const file of sources(src)) {
  if (file === seam) continue;
  if (eeRoots.some((root) => file.startsWith(root + "/"))) continue;

  for (const specifier of specifiers(readFileSync(file, "utf8"))) {
    const target = resolveSpecifier(specifier, file);
    if (target && eeRoots.some((root) => target === root || target.startsWith(root + "/"))) {
      violations.push(`${relative(src, file)} -> ${specifier}`);
    }
  }
}

if (violations.length > 0) {
  console.error(
    `edition boundary: ${violations.length} import(s) cross into the ee plugin.\n` +
      `route them through src/lib/edition.ts instead.\n`,
  );
  for (const violation of violations) console.error(`  ${violation}`);
  process.exit(1);
}

console.log("edition boundary: ok");
