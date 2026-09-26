---
name: documentation-update
description: >
  Keep qbrix's public documentation (docs/*.mdx, rendered at qbrix.io/docs by the marketing site in ../qbrix-www) in sync with
  the code it describes. Runs in two modes. CHECK mode: audit the docs against their sources of
  truth — policy catalog, API endpoints, plan/RBAC tables, cache/batch numbers, gate operators,
  SDK signatures — and report what has drifted. UPDATE mode: propose the exact doc edits for the
  drift and apply them on approval. Trigger when: (1) the user asks to check / audit / verify the
  docs are up to date; (2) the user asks to update or fix the docs; (3) after a change to policies,
  endpoints, plan tiers/limits, RBAC scopes, cache/batch config, gate rules, event/retention, or
  the SDKs, to confirm the docs still hold. For a broad cross-repo change sweep use change-impact;
  for legal pages use legal-audit/legal-impact.
---

# Docs Sync

Verify, fact by fact, that qbrix's public docs still match the code — then fix the drift.

The reference is **`fact-map.md`** in this skill directory: every user-facing claim in
`docs/*.mdx`, mapped to its source of truth in code (and the two external SDK repos). **Read it
first** — it is the source of truth for this skill.

Two modes. Infer from the request; if ambiguous, ask.
- **CHECK** ("is the doc up to date", "audit the docs", "did X change the docs") → Steps 1–3, stop at the report.
- **UPDATE** ("update the docs", "fix the drift") → run CHECK, then Steps 4–5.

## Step 0 — Scope the run

- **Full audit** (default for CHECK): every doc, every fact in the fact-map.
- **Change-scoped** (when the user named a diff/PR/area, or this follows a code change): resolve
  the change set — `git diff --name-only main...HEAD`, plus `git status --porcelain` and
  `git diff --name-only` for uncommitted work — then intersect it with the fact-map **Watch list**
  and verify only the docs it points to. Still run the structural checks (S1–S4), they are cheap.

## Step 1 — Structural checks (always)

From `fact-map.md` "Structural invariants":
- **S1/S2** — reconcile `../qbrix-www/apps/www/src/config/docs.ts` slugs against the `docs/*.mdx` files.
  A configured slug with no file breaks the sidebar; an unlisted file is unreachable.
- **S3/S4** are automated: `cd web && pnpm check-docs` also compiles every page and checks its
  frontmatter. Run it first; the notes below are for reading its output.
- **S3** — every `](/docs/<slug>)` internal link resolves to a real doc (`grep -ro '](/docs/[a-z-]*' docs`).
- **S4** — every `#anchor` link resolves to a real heading slug in the target doc. Remember
  `rehype-slug` derives ids from heading **text** (`### BetaTSPolicy` → `#betatspolicy`), so
  descriptive anchors like `#beta-thompson-sampling` are broken. (Known offender: `use-cases.mdx`.)
- **S5** — a doc only uses MDX components defined in `components/docs/mdx-components.tsx`.

## Step 2 — Verify each fact

Walk the fact-map. For each fact, open **both** the doc claim and its **source of truth** at the
grep anchor (not line numbers — they drift), and confirm they agree. Prioritise the high-drift
table (D1–D12) and the policy catalog:

- **D1 plan tiers / D2 RBAC scopes** — read `svc/proxy/src/proxysvc/mod/auth/scope.py`
  (`PLAN_LIMITS`, `TIER_ORDER`, `ROLE_SCOPES`). Every plan table and scope count must match. (These
  are currently drifted — the docs show 3–4 tiers, the code has 5.)
- **Policy catalog** — for every policy in `policies.mdx`, confirm the class exists in
  `lib/core/qbrixcore/policy/` and its documented params (name/type/default/required), reward
  type(s), and category match the class's `PolicyParam` metadata / `reward_types` / `category`.
  No documented policy missing from the registry; no registered policy missing from the docs.
- **Endpoints** — every `<Endpoint>` in `api-reference.mdx` exists in
  `svc/proxy/src/proxysvc/transport/http/router/*.py`; no developer endpoint undocumented.
- **Cache / batch numbers (D3–D8)** — motor `config.py`/`cache.py`, cortex `config.py`/`dispatcher.py`.
- **Gate operators** — the operator tables vs `svc/proxy/src/proxysvc/mod/gate/model/rule.py`.
- **SDK facts** — read `../qbrix-python` and `../qbrix-js` when present (package name/version, min
  runtime, resource→method tables, config defaults, error classes). Flag findings as **external**:
  they live outside this repo, so the doc is right/wrong relative to a separately-versioned package.
  If a sibling repo is absent, mark those facts ⚠️ external-unverified.

## Step 3 — Report

Output a status table over the facts you checked (group by doc). One row per fact:

```
## Docs sync — CHECK (<scope>)

| Doc | Fact | Status | Note |
|-----|------|--------|------|
| features.mdx | D1 plan tiers | ❌ drifted | doc: Free/Pro/Enterprise (3); scope.py PLAN_LIMITS: free/starter/growth/scale/enterprise (5) |
| use-cases.mdx | S4 policy anchors | ❌ broken | #beta-thompson-sampling → real slug is #betatspolicy |
| policies.mdx | GLMUCB alpha default | ✅ in sync | 1.5 matches class |
| python-sdk.mdx | config defaults | ⚠️ external | verify vs ../qbrix-python/qbrix/_config.py |
```

Statuses: ✅ in sync · ❌ drifted (doc now inaccurate) · ⚠️ external (outside this repo — SDK repos)
· ⚠️ external-unverified (sibling repo not available). End with a count of drifted facts and the
exact edits each needs. In CHECK mode, **stop here** and offer to run UPDATE.

## Step 4 — Propose edits (UPDATE mode)

For every ❌ finding, draft the concrete edit: the file, the current text, the corrected text, and
the source anchor that justifies it. Present them as a batch for approval **before** touching any
file. Keep the doc's voice, tables, and callout style — change only what the source of truth
requires. Cross-doc facts (a plan table appears in more than one doc) must be fixed **consistently
everywhere** — search all docs for the same claim.

Judgment calls stay with the user: rewording marketing/positioning prose, adding or removing whole
sections, and any **code example** change (a wrong snippet can subtly break) — show these and let
the user decide rather than silently rewriting. Mechanical facts (a number, a tier name, an
endpoint path, a scope list, a broken anchor) can be fixed directly once approved.

For **external** (SDK) drift, do not edit the sibling repos from here — fix the doc to match the
published package, or, if the package itself is wrong, surface that as a separate SDK-repo task.

## Step 5 — Apply and verify

On approval, apply the edits with `Edit`. Then:
- Re-run Step 1 structural checks and re-verify the specific facts you changed.
- Run `cd web && pnpm check-docs`: it compiles every page, checks the frontmatter the site reads
  (`title`, `description`, `order`) and resolves every `/docs/...` link and anchor. An undefined
  MDX component only surfaces in the site build: if `../qbrix-www` is checked out, build it there
  (`pnpm build`, which reads `../qbrix/docs`).
- Summarise what changed, what was left for the user (judgment calls, external/SDK items), and any
  follow-up (e.g. reconcile `growth`/`scale` tier names with the pricing page and Stripe).

Do not commit or open a PR unless asked — report the edits and let the user drive that.
