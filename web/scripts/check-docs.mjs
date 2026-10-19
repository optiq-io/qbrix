#!/usr/bin/env node
//
// the docs are rendered by the marketing site, which builds in another repo, so
// a broken page here would otherwise surface only on its next deploy. this
// compiles every page the way the site does (mdx 3 + remark-gfm), checks the
// frontmatter the site reads, and resolves every `/docs/...` link and anchor.
// anchors are github-slugger slugs of heading text, which is what rehype-slug
// assigns.
//
//   check-docs.mjs [dir] [fallback-dir...]
//
// only the first dir is checked. fallback dirs are read to resolve its links, so
// docs-next/ can link to pages that stay in docs/; a page in the checked dir
// shadows one with the same slug in a fallback.

import { readdirSync, readFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "@mdx-js/mdx";
import GithubSlugger from "github-slugger";
import matter from "gray-matter";
import remarkGfm from "remark-gfm";

const here = dirname(fileURLToPath(import.meta.url));
const [docsDir, ...fallbackDirs] = (
  process.argv.length > 2 ? process.argv.slice(2) : [join(here, "..", "..", "docs")]
).map((dir) => resolve(dir));

function text(node) {
  if (typeof node.value === "string" && node.type !== "mdxjsEsm") return node.value;
  return (node.children ?? []).map(text).join("");
}

function walk(node, visit) {
  visit(node);
  for (const child of node.children ?? []) walk(child, visit);
}

function collect(page) {
  return () => (tree) => {
    const slugger = new GithubSlugger();
    walk(tree, (node) => {
      if (node.type === "heading") page.anchors.add(slugger.slug(text(node)));
      if (node.type === "link") page.links.push({ url: node.url, line: node.position?.start.line });
      if (node.type === "mdxJsxFlowElement" || node.type === "mdxJsxTextElement") {
        for (const attr of node.attributes ?? []) {
          if (typeof attr.value !== "string") continue;
          if (attr.name === "id") page.anchors.add(attr.value);
          if (attr.name === "href") page.links.push({ url: attr.value, line: node.position?.start.line });
        }
      }
    });
  };
}

const errors = [];
const pages = new Map();
const fallbackPages = new Map();

async function load(dir, into, report) {
  for (const file of readdirSync(dir).filter((f) => f.endsWith(".mdx")).sort()) {
    into.set(file.replace(/\.mdx$/, ""), await read(dir, file, report));
  }
}

async function read(dir, file, report) {
  const raw = readFileSync(join(dir, file), "utf-8");
  const page = { anchors: new Set(), links: [] };

  let parsed;
  try {
    parsed = matter(raw);
  } catch (err) {
    report(`${file}: frontmatter does not parse: ${err.message}`);
    return page;
  }
  const { data, content } = parsed;
  for (const key of ["title", "description"]) {
    if (typeof data[key] !== "string" || !data[key].trim()) {
      report(`${file}: frontmatter \`${key}\` must be a non-empty string`);
    }
  }
  if (typeof data.order !== "number") report(`${file}: frontmatter \`order\` must be a number`);

  const frontmatterLines = raw.slice(0, raw.length - content.length).split("\n").length - 1;
  try {
    await compile("\n".repeat(frontmatterLines) + content, {
      remarkPlugins: [remarkGfm, collect(page)],
    });
  } catch (err) {
    report(`${file}: ${err.reason ?? err.message}`);
  }
  return page;
}

await load(docsDir, pages, (error) => errors.push(error));
for (const dir of fallbackDirs) await load(dir, fallbackPages, () => {});

const searched = [docsDir, ...fallbackDirs].map((dir) => basename(dir) + "/").join(" or ");

for (const [slug, page] of pages) {
  for (const { url, line } of page.links) {
    const where = `${slug}.mdx${line ? `:${line}` : ""}`;
    const [path, anchor] = url.split("#", 2);
    let target = slug;
    if (path) {
      const match = path.match(/^\/docs\/([^/?]+)\/?$/);
      if (!match) continue;
      target = match[1];
    }
    const targetPage = pages.get(target) ?? fallbackPages.get(target);
    if (!targetPage) errors.push(`${where}: link to ${url}: no ${target}.mdx in ${searched}`);
    else if (anchor && !targetPage.anchors.has(anchor)) {
      errors.push(`${where}: link to ${url}: no heading #${anchor} in ${target}.mdx`);
    }
  }
}

if (errors.length) {
  console.error(errors.join("\n"));
  console.error(`\n${errors.length} problem(s) in ${docsDir}`);
  process.exit(1);
}
console.log(`${pages.size} docs pages compile and every docs link resolves`);
