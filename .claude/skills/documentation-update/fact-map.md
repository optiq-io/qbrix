# Docs Fact Map

Every user-facing claim in the qbrix public docs (`docs/*.mdx`), mapped to its **source of
truth in code**. When the source changes, the doc may become inaccurate. This is the reference
for the `documentation-update` skill (both check and update modes).

## How docs reach the site

`docs/*.mdx` live at the repo root and are rendered **directly** by the marketing site — there is
no copy/build step, the site reads the source files:

The site lives in the private `../qbrix-www`; its build reads `docs/` from this repo's `main`. The
site-side paths below exist only when that checkout is present. Without it, report S1/S2/S5 as
skipped rather than passed.

- Loader: `../qbrix-www/apps/www/src/lib/docs.ts` → `getDocBySlug` reads `DOCS_DIR/<slug>.mdx`, by default
  the sibling checkout `../qbrix/docs`. `getAllDocs` renders **every** `.mdx` file in `docs/`.
- Route: `../qbrix-www/apps/www/src/app/docs/[slug]/page.tsx` → `/docs/<slug>` (static, `generateStaticParams`).
- Sidebar / nav order: `../qbrix-www/apps/www/src/config/docs.ts` (`docSections`, `allDocSlugs`).
- MDX components in use (a doc may only use these): `../qbrix-www/apps/www/src/components/docs/mdx-components.tsx`
  — `Callout`, `CodeTabs`/`CodeTab`, `Endpoint`, `FeatureGrid`/`FeatureCard`, `Badge`,
  `PolicyFlowchart`. Headings get ids via `rehype-slug` (slug = lowercased heading text,
  non-alphanumerics → `-`).

**Structural invariants** (check these first, they break the build or the nav):

| # | Invariant | Source of truth |
|---|-----------|-----------------|
| S1 | Every slug in `config/docs.ts` has a matching `docs/<slug>.mdx` | `config/docs.ts` ↔ `docs/` listing. A missing file breaks the sidebar link. |
| S2 | Every `docs/<slug>.mdx` is either in `config/docs.ts` or intentionally unlisted | orphan `.mdx` still renders at `/docs/<slug>` but is unreachable from the sidebar |
| S3 | Every internal link `/docs/<slug>` resolves to a real doc | grep `](/docs/` across `docs/*.mdx` |
| S4 | Every in-page anchor `/docs/<slug>#<id>` resolves to a heading slug in the target doc | `rehype-slug` derives ids from heading **text**, not the class name — e.g. `### BetaTSPolicy` → `#betatspolicy`, **not** `#beta-thompson-sampling` |
| S5 | A doc only uses MDX components that exist in `mdx-components.tsx` | `../qbrix-www/apps/www/src/components/docs/mdx-components.tsx` |
| S6 | Frontmatter `order` values give a sensible reading order | per-file frontmatter vs `config/docs.ts` section order |

> S4 example: descriptive anchors like `#beta-thompson-sampling` / `#ucb1-tuned` do **not** match the
> real `policies.mdx` heading slugs (`#betatspolicy`, `#ucb1tunedpolicy`, …). Likewise `#tracesvc`
> must be `#tracesvc-enterprise` (heading is `### tracesvc (Enterprise)`). Fixed 2026-07 — re-check on
> any new policy cross-links.

Cite sources by **file + search anchor** (grep string), not line number alone — line numbers drift.

---

## High-drift-risk facts (hardcoded numbers / tables the docs quote verbatim)

These are the facts most likely to silently drift. Verify the doc's number against the anchor.

| # | Fact in docs | Doc location | Source of truth (anchor) |
|---|--------------|--------------|--------------------------|
| D1 | Plan tiers + RPM + API-key + seat + active-experiment limits | `console-workspace.mdx` table; `plans-and-limits.mdx` "Plans" + "Rate limits" | `svc/proxy/src/proxysvc/mod/auth/scope.py` → `PLAN_LIMITS`, `PAID_TIERS`, `TIER_ORDER` |
| D2 | RBAC scope matrix; "Admin 19 / Member 18 / Viewer 7 scopes" | `plans-and-limits.mdx` "Roles & permissions"; `console-workspace.mdx` Roles table | `scope.py` → `ROLE_SCOPES` |
| D3 | Agent cache 300s TTL / 100 entries; param cache 60s TTL / 1000 entries | `architecture.mdx` "Timings" table (surfaced as user-facing windows: 60s params / 5 min config), `feedback-and-rewards.mdx` (60s) | `svc/motor/src/motorsvc/config.py` + `svc/motor/src/motorsvc/cache.py` (CLAUDE.md: `MOTOR_AGENT_CACHE_*`, `MOTOR_PARAM_CACHE_*`) |
| D4 | Gate cache L1 30s TTL / 1000 entries, L2 Redis 300s | `architecture.mdx` "Timings" row "Feature gate change → up to 30s" (worst case = another replica's L1 TTL; a write pushes L2 immediately and only invalidates local L1) | proxy gate cache (`svc/proxy/src/proxysvc/core/cache/`, `mod/gate/`); CLAUDE.md `PROXY_GATE_CACHE_MAXSIZE/_TTL`, `PROXY_GATE_REDIS_TTL` |
| D5 | Cortex batch 256, 100ms timeout, 4 workers, 10s flush | **no longer asserted in docs** (deliberately internal as of the 2026-07 de-internalisation) — docs say only "trained in batches, per experiment". Do not reintroduce the numbers. | `svc/cortex/src/cortexsvc/config.py` + `dispatcher.py` (CLAUDE.md `CORTEX_BATCH_SIZE`, `_BATCH_TIMEOUT_MS`, `_NUM_WORKERS`, `_FLUSH_INTERVAL_SEC`) |
| D6 | "100-thread gRPC pool" per service | **no longer asserted in docs** (internal; gRPC is not a user-facing concept) | service bootstrap `grpc.server(ThreadPoolExecutor(max_workers=...))` in each `svc/*/src/*/service.py` |
| D7 | Rate-limit counters expire after 120s; apply only to `select`/`feedback` | `architecture.mdx` "Rate limits protect the hot path only", `plans-and-limits.mdx` | proxy rate limiter (`svc/proxy/src/proxysvc/mod/agent/` or `core/`); `scope.py` `ABUSE_RATE_LIMIT_PER_MINUTE` (=6000) |
| D8 | Param update propagates **within 60 seconds** | `feedback-and-rewards.mdx` callout; `architecture.mdx` "Timings" | bounded by param cache TTL (D3, 60s). Corrected 2026-07 from the old "~30 seconds" claim, which was below the actual TTL. |
| D9 | Event Log retention = **flat 90 days**, uniform across tiers | `console-event-log.mdx` | `lib/store/qbrixstore/clickhouse/migrations.py` → `create_tables(ttl_days=90)` applies one `event_date + INTERVAL 90 DAY` TTL to all event tables. **Confirmed 2026-07**: no per-tier retention in code, and `qbrix-iac` sets no ClickHouse TTL. Do not reintroduce a per-tier table without a real source. |
| D10 | Invite link expiry — **72 hours** | `console-workspace.mdx` | `svc/proxy/src/proxysvc/mod/auth/service.py` → `expires_at = datetime.now(timezone.utc) + timedelta(hours=72)`. **Corrected 2026-08**: both the doc and this row previously said 7 days. The `Invite.expires_at` column stores whatever the issuer computed — it is not the source of the window. |
| D11 | API key prefix `optiq_` | `getting-started.mdx`, `python-sdk.mdx`, `javascript-sdk.mdx`, `console-workspace.mdx`, `api-reference.mdx` | `svc/proxy/src/proxysvc/mod/auth/service.py` → `_api_key_prefix = "optiq_"` |
| D12 | Base URL `https://cloud.qbrix.io`; API prefix `/api/v1` | `api-reference.mdx`, all quickstarts | `web/apps/console` deploy domain; proxy router mount prefix (`transport/http/`) |

> D1/D2 reality (verified 2026-07): `PLAN_LIMITS` has **five** tiers
> (`free, starter, growth, scale, enterprise`); the differentiator is `included_selections_per_month`
> (100K/1M/10M/50M/∞) and **only `free` is capped** on keys(2)/seats(3)/experiments(3) — all paid tiers
> are `-1` (unlimited). There is **no per-tier RPM**; rate limiting is a flat `ABUSE_RATE_LIMIT_PER_MINUTE`.
> `ROLE_SCOPES` counts: admin **20**, member **16**, viewer **8**, and the hierarchy
> admin ⊇ member ⊇ viewer holds (enforced by `test_role_scopes_are_hierarchical`). The former
> `insight:write`-missing-from-admin quirk was a real bug, since fixed. One quirk remains that
> the docs mirror faithfully: paid tiers carry no hard resource caps. Flag it, don't "fix" it in docs.

---

## Per-doc fact map

### `getting-started.mdx` (Quickstart) · `introduction.mdx`
- Install: `pip install qbrix`, `npm install @optiqio/qbrix` → external (SDK section).
- Client init signatures, `auto` default, `policy_params={"reward_type": ...}` → qbrix-python `_client.py`/`_config.py`, qbrix-js `client.ts`.
- Select response shape `{request_id, arm:{id,name,index}, is_default}` → `svc/proxy/src/proxysvc/transport/http/router/agent.py` + response model / proto.
- "Python SDK wraps every endpoint; JS SDK is select+feedback only" → external (must stay true vs the two repos).

### `architecture.mdx` (titled "How qbrix works")
**Rewritten 2026-07 to contain no service names, no infra nouns, and no topology.** It now asserts only
user-facing contracts. Keep it that way: `proxysvc`/`motorsvc`/`cortexsvc`/`tracesvc`, Redis, Postgres,
ClickHouse, gRPC and Kubernetes must not reappear here. Service topology lives in `CLAUDE.md` and the
`/architecture` **marketing** page, not in docs.
- **Timings table** — these four rows are the whole of D3/D4 as far as docs are concerned. Verify against
  `svc/motor/src/motorsvc/config.py` (`param_cache_ttl=60`, `agent_cache_ttl=300`) and
  `svc/proxy/src/proxysvc/config.py` (`gate_cache_ttl=30.0`). Note `MotorCache.invalidate_experiment`
  has **no production caller**, so a config change really does wait out the full 300s agent TTL.
- **Guarantees** (no feedback lost / fail-safe gate / stateless correlation / rate limits) →
  `svc/cortex/` recovery, `mod/gate/` fail-safe, `mod/agent/` HMAC token, `scope.py`
  `ABUSE_RATE_LIMIT_PER_MINUTE`.
- The two `<Flow>` diagrams replaced `selection-path.png` / `learning-path.png`, which named services.
  The stale PNGs still sit in `../qbrix-www/apps/www/public/` — don't re-reference them.

### `pools-and-experiments.mdx`
- Arm fields (`name`, auto `index` 0-based, `metadata`); "arms immutable after creation"; "pool needs ≥2 arms"; "pool name unique per workspace"; "can't delete pool with active experiments" → `lib/store/qbrixstore/postgres/models.py` (`Pool`, `Arm`, `Experiment`) + validation in `svc/proxy/src/proxysvc/mod/pool/` and `mod/experiment/`.
- Experiment fields (`name`, `pool_id`, `policy`, `policy_params`, `enabled` default true).
- "Disabled → default arm (index 0)"; "changing policy_params resets learned state" → `mod/experiment/` service + cortex/param backend behavior.

### `policies.mdx` · `auto-policy.mdx` (the largest verify surface)
- The **policy catalog**: for every policy, verify class exists, its **param names / types / defaults / required**, its **reward type(s)**, and its **category**. Source of truth:
  `lib/core/qbrixcore/policy/` — each policy class + its `PolicyParam` metadata (`user_params()`),
  `category: ClassVar[str]`, `reward_types: ClassVar[list[RewardType]]`. Registry/exports in
  `lib/core/qbrixcore/policy/__init__.py` and `policy/_meta.py`.
- Policies documented (must match the registry — no missing, no extra): BetaTSPolicy, DiscountedTSPolicy, GaussianTSPolicy, UCB1TunedPolicy, KLUCBPolicy, EpsilonPolicy, MOSSPolicy, MOSSAnyTimePolicy, RandomPolicy (stochastic); LinUCBPolicy, LinTSPolicy, LogisticTSPolicy, GLMUCBPolicy (contextual); EXP3Policy, EXP3IXPolicy, FPLPolicy (adversarial).
- `auto`: `MetaBanditPolicy` (EXP3 meta), N+1 experiments, portfolio scoped by `reward_type`/`use_context`/`dim` → `lib/core/qbrixcore/policy/` (meta policy) + auto-experiment fan-out in `svc/proxy/src/proxysvc/mod/experiment/` (or `mod/agent/`).
- `GET /api/v1/policies` returns this catalog → `svc/proxy/src/proxysvc/transport/http/router/policy.py`.
- Common trap: param **default values** in the doc tables (e.g. `alpha=1.5` for GLMUCB, `gamma` required for DiscountedTS, `n_horizon=1000` MOSS) — verify each against the class.

### `feedback-and-rewards.mdx`
- Reward-type → policy mapping (which policies take binary/continuous/bounded) → each policy's `reward_types` (must agree with `policies.mdx`).
- Async pipeline numbers → D5 + D3. Token "no expiration / tamper-proof HMAC" → proxy agent token (`mod/agent/`).

### `contexts.mdx`
- Context object `{id?, vector?, metadata?}`, "vector length must match `context_dim`", "stochastic policies ignore vector", "metadata used only by gate rules" → `lib/core/qbrixcore` `Context`; proxy select validation; qbrix Context model.

### `feature-gates.mdx`
- Resolution order: enabled → schedule → rules (first match with `arm_id` wins; ruleless opts into policy) → rollout hash on request id → `svc/proxy/src/proxysvc/mod/gate/` (controller/service).
- "at most one gate per experiment"; `is_default` flag; fail-safe returns `None` → `mod/gate/`.
- **Operators** (the two operator tables must match, and the "15+ operators" claim): `svc/proxy/src/proxysvc/mod/gate/model/rule.py` (`OperatorType`). `feature-gates.mdx` now carries the single canonical operator table with an Aliases column; verify it against the enum. Note `contains`/`not_contains`/`in`/`not_in` have no aliases.

### `api-reference.mdx`
- Every `<Endpoint method path>` must exist with that method+path, and no developer-facing endpoint should be undocumented. Source: `svc/proxy/src/proxysvc/transport/http/router/{pool,experiment,agent,gate,policy}.py` (+ `runtime.py`). Note `POST /experiments/{id}/reset` requires `experiment:write` and 409s when running (scope in `scope.py` `ENDPOINT_SCOPES`).
- Header is `X-API-Key`; keys inherit creator's role → `mod/auth/`.

### `console-experiments.mdx` · `console-event-log.mdx` · `console-workspace.mdx`
- These describe **console UI**; source of truth = `web/apps/console/src/app/`:
  `experiments/`, `developers/event-log/`, `settings/` (Profile/API Keys/Workspace/Billing tabs), `invite/`.
- `console-workspace.mdx`: plan table = D1; invite expiry = D10; `optiq_` = D11; roles = D2.

**Console UI controls — the highest-drift surface in the docs, and the easiest to miss.** These are
navigation instructions: the reader is looking at them to find a control on their own screen. A
column list or a button label that no longer matches reads as a missing feature. Every one of the
rows below was wrong when first audited because this section named no anchors. Name the
constant, not the page.

| Doc claim | Anchor (grep string) | File |
|---|---|---|
| Experiments list columns | `const COLUMNS` (EE) and `const CORE_COLUMNS` (EE off) | console `app/(app)/page.tsx` |
| Filter tabs `All / Active / Paused` | `filterTabs` | same |
| `New experiment` button | `New experiment` | same |
| Status badge `Running` / `Paused` | `exp.enabled ?` | same |
| Experiment detail tabs | directory listing of `app/(app)/experiments/[id]/` | — |
| Event log categories | `const CATEGORIES` | `developers/event-log/page.tsx` |
| Event log time ranges | `const RANGES` | same |
| Event log columns | `EVENT_COLUMNS` | `developers/event-log/row.tsx` |
| Stream dot colours | `STREAM_DOT` | `developers/event-log/derive.ts` |
| Settings tabs | `const LABELS` / `BASE_TABS` | `app/(app)/settings/page.tsx` |
| API key menu items (`Rotate key`, `Revoke key`) | `label: "Rotate key"` | `components/settings/api-keys-tab.tsx` |
| `Create API key` button | `Create API key` | `app/(app)/settings/page.tsx` |

- **The event log has no Actor filter and no free-text search** — the `Search` icon decorates the
  experiment `<select>`. The docs once claimed both. Do not reintroduce them without a
  matching control in `page.tsx`.
- **`FeedbackEvent` carries no latency field** (`lib/store/qbrixstore/event/feedback.py`), and the
  console deliberately did not build the board's `LAT` column. Any "time delta from selection" or
  lag claim is unsupported — see also F3, which bans latency figures site-wide.
- `console-event-log.mdx`: three streams (selection/feedback/audit) → `lib/store/qbrixstore/event/`;
  retention = D9.
- The two console figures in these docs are **DOM components**, not screenshots
  (`../qbrix-www/apps/www/src/components/docs/console-figures.tsx`). They copy the column sets above
  verbatim — when a column set changes, the figure changes with it.

### `sdks.mdx` · `python-sdk.mdx` · `javascript-sdk.mdx` · SDK code in `use-cases.mdx`
- **External sources of truth** (sibling repos, outside this monorepo — read them, but flag findings as "external"):
  - Python: `../qbrix-python/` — `pyproject.toml` (name `qbrix`, version, `requires-python`), `qbrix/resource/{pool,experiment,gate,agent,policy}.py` (method names), `qbrix/_config.py` (defaults: `QBRIX_BASE_URL` `http://localhost:8080`, `QBRIX_TIMEOUT` `30.0`, `QBRIX_MAX_RETRIES` `3`), `qbrix/exception.py` (`NotFoundError`, `RateLimitedError`, …), `qbrix/model/common.py` (`Context`).
  - JS: `../qbrix-js/` — `package.json` (name `@optiqio/qbrix`, version, `engines.node` `>=18`, ESM+CJS), `src/client.ts` (`select`/`feedback` signatures), `src/config.ts` (defaults: baseUrl `http://localhost:8080`, timeout `30000`, maxRetries `2`, retryOn `[429,502,503,504]`), `src/errors.ts` (`QbrixError` hierarchy: `QbrixAPIError`/`RateLimitedError`/`AuthenticationError`/`QbrixTimeoutError`/`QbrixConnectionError`, status subclasses), `src/types.ts` (`Context`, `SelectResult`).
- Facts to verify: package names, min runtime versions, resource→methods tables (`pool: create/get/list/delete`, `gate: create/get/update/delete`, `agent: select/feedback`), config default values, error class lists.
- **Trap**: `python-sdk.mdx` shows `gate.create(experiment_id=, enabled=, rollout_percentage=, default_arm_id=, rules=)` while `use-cases.mdx` calls `qbrix.gate.create(name=..., experiment_id=..., rollout_percentage=...)` with a `name` kwarg — verify the real signature in `qbrix/resource/gate.py` and reconcile.

### `use-cases.mdx`
- Illustrative Python snippets: verify method signatures against qbrix-python (see gate trap above), policy names against the registry, and the "Recommended policies" anchor links against S4.
- Positioning claims (adaptive optimization vs A/B testing) → messaging is owned by marketing, not code; leave prose alone unless it states a wrong capability.

---

## Watch list — code changes that should trigger a `documentation-update` check

If a change set touches any of these, re-verify the listed docs:

| Changed source | Re-check docs |
|----------------|---------------|
| `lib/core/qbrixcore/policy/**` (new/removed policy, param/default/reward-type change) | `policies.mdx`, `auto-policy.mdx`, `feedback-and-rewards.mdx` |
| `svc/proxy/src/proxysvc/mod/auth/scope.py` (`PLAN_LIMITS`, `ROLE_SCOPES`, tiers) | `plans-and-limits.mdx`, `console-workspace.mdx`, `console-event-log.mdx` (D9) |
| `svc/proxy/src/proxysvc/transport/http/router/**` (endpoints) | `api-reference.mdx`, `getting-started.mdx` |
| `svc/proxy/src/proxysvc/mod/gate/**` (`rule.py` operators, resolution) | `feature-gates.mdx` |
| `svc/motor/**/config.py`, `cache.py` (cache TTLs/sizes) | `architecture.mdx`, `feedback-and-rewards.mdx` |
| `svc/cortex/**/config.py`, `dispatcher.py` (batch/workers/flush) | `architecture.mdx`, `feedback-and-rewards.mdx` |
| `lib/store/qbrixstore/postgres/models.py` (Pool/Arm/Experiment/Invite fields) | `pools-and-experiments.mdx`, `console-workspace.mdx` |
| `lib/store/qbrixstore/clickhouse/migrations.py` (`ttl_days`) | `console-event-log.mdx` (D9) |
| `lib/store/qbrixstore/redis/events.py` (event types/fields) | `console-event-log.mdx`, `architecture.mdx` |
| `../qbrix-www/apps/www/src/config/docs.ts` (sidebar) | S1/S2 — reconcile with `docs/` files |
| `web/apps/console/src/app/**` (console pages) | `console-*.mdx` |
| `../qbrix-python/**`, `../qbrix-js/**` (external) | `sdks.mdx`, `python-sdk.mdx`, `javascript-sdk.mdx`, `use-cases.mdx` |

---

## External facts (cannot be verified from the qbrix monorepo alone)

- **SDK method names, defaults, versions, error classes** — `../qbrix-python`, `../qbrix-js` (read when present; flag as external).
- **Live domain / base URL** (`cloud.qbrix.io`) — deploy config in `qbrix-iac`.
- **Pricing tier marketing names** — reconcile code tiers (`growth`/`scale`) with the pricing page `../qbrix-www/apps/www/src/app/pricing/` and Stripe objects; the docs and the pricing page must agree.
