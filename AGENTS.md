# AGENTS.md

Guidance for anyone, human or coding agent, working in this repository: the
architecture, where things live, the conventions, and the commands.
[`CONTRIBUTING.md`](CONTRIBUTING.md) covers the contribution process.

## Project overview

qbrix is a distributed system for multi-armed bandit optimization. It separates the
hot path (selection) from the learning path (training), so decisions stay
low-latency while parameter updates are eventually consistent.

## Architecture

```
                              ┌─────────────────────────────────────┐
                              │               proxy                 │
                              │  - REST + gRPC API, auth, RBAC      │
                              │  - experiments, pools, gates        │
                              │  - cloud edition plugin (ee)        │
                              └──────────┬──────────────────────────┘
                                         │ gRPC
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
            ┌───────────────┐    ┌───────────────┐    ┌───────────────┐
            │     motor     │    │     motor     │    │     motor     │
            │  (selection)  │    │  (selection)  │    │  (selection)  │
            └───────┬───────┘    └───────┬───────┘    └───────┬───────┘
                    └────────────────────┼────────────────────┘
                                         │ read (TTL cache via cachebox)
                                         ▼
                              ┌─────────────────────┐
                              │  Redis (params)     │
                              └─────────────────────┘
                                         ▲ write (batch)
                              ┌─────────────────────┐
                              │  cortex (training)  │
                              └──────────┬──────────┘
                                         │ consume
                              ┌─────────────────────┐
                              │   Redis Streams     │
                              │ feedback, selection,│
                              │ audit               │
                              └─────────────────────┘
                                         ▲ publish
                                       proxy ──► Postgres (experiments, pools,
                                                 tenants, users, billing)
```

### Services

**proxy** (`svc/proxy`): gRPC 50050, HTTP 8080
- Entry point for every client request: gRPC internally, REST (FastAPI) externally.
- Owns experiments, pools and feature gates in Postgres; routes selection to motor.
- Publishes feedback, selection and audit events to Redis Streams.
- Auth: JWT tokens and API keys (prefix `optiq_`). Roles: admin, member, viewer.
- Multi-tenant: the tenant is resolved from the authenticated principal, never from
  a header.
- `ProxyRuntime` (`proxysvc/runtime.py`) is the composition root: it owns Redis,
  `ProxyService`, `AuthService`, the invalidation bus and, in the cloud edition,
  `BillingService`, and starts and stops them in one place. `cli.py` only parses
  arguments and builds transports on a started runtime, so `serve-grpc`,
  `serve-http` and `serve` share one wiring and one teardown.
- Entitlement invalidation: a tier change publishes the tenant id on the Redis
  pub/sub channel `qbrix:invalidate:tenant` (`qbrixstore/channel.py`), and every
  replica evicts its principal, tier and usage caches. Delivery is best-effort; the
  caches' TTLs are the backstop. Anything else caching per-tenant entitlements
  should subscribe to this channel through `BroadcastBus`
  (`qbrixstore/redis/pubsub.py`) rather than add a second mechanism.
- `PROXY_RUNENV=dev` bypasses auth and seeds a dev user. That user is synthetic,
  so nothing that depends on a real tenant can be tested in dev mode.

**motor** (`svc/motor`): gRPC 50051
- The hot path: arm selection only. Stateless and horizontally scalable.
- Reads parameters from Redis through a TTL cache (cachebox), so allocation moves
  on cache refresh, not per request.

**cortex** (`svc/cortex`): gRPC 50052
- Consumes feedback from Redis Streams, trains in batches, writes parameters back
  to Redis. Off the hot path.
- **One instance by design**: training is event-sourced, and two trainers would
  race on the same parameters.

**trace** (`svc/trace`): gRPC 50053, optional (the analytics switch)
- Consumes all three streams and writes them to ClickHouse for the insight and
  event endpoints.
- Scales horizontally: writes are append-only, and the `trace` consumer group
  delivers each entry to one replica. `TRACE_CONSUMER_NAME` must differ per replica.
- Batches live in memory until flushed, and on `qbrix:feedback` cortex's ack may
  already have deleted the entries from the stream, so the drain on `stop()` is
  their last copy.

**meter** (`ee/svc/meter`): gRPC 50054, cloud edition only
- Consumes `qbrix:selection` under its own `metering` group, sums selections per
  `(tenant, time bucket)`, and emits one Stripe meter event per bucket.
- **One instance by design**: replicas would split a bucket and each emit a partial
  sum under the same idempotency key, which Stripe dedups into an undercount.
- Acks only after Stripe accepts, so a crash or outage drains on recovery without
  double counting.

### Editions

Two independent switches:

- **`PROXY_EE_ENABLED`** loads the cloud plugin `proxysvc/ee/`: billing, plan tiers
  (`ee/plans.py`), the selection quota (`ee/metering/`), `PlanEntitlements`. Core
  reads plans only through `core/entitlements.Entitlements`; self-hosted gets
  `UnlimitedEntitlements` (no caps, no quota).
- **`PROXY_ANALYTICS_ENABLED`** mounts the insight and event routes and turns on
  the selection and audit streams. Needs trace and ClickHouse.

`proxysvc/edition.py` is the only core module that may name `proxysvc.ee`. It
imports nothing from it when EE is off, and fails at boot if EE is on but the
package is absent. In the console, `src/lib/edition.ts` is the only core file that
may import `src/ee` or `src/app/(ee)`; the gate vocabulary (`useEntitlements`,
granted / locked / absent) is in `src/lib/entitlements.ts`. Every cloud-only path
is listed in `bin/ee-paths.txt`, and CI deletes them all and runs the suite.

### HTTP API (`/api`)

| Prefix | Description |
|--------|-------------|
| `/api/v1/pools` | pool CRUD |
| `/api/v1/experiments` | experiment CRUD |
| `/api/v1/gates` | feature gates |
| `/api/v1/agent` | `/select` and `/feedback` |
| `/api/v1/policies` | policy catalog with parameters |
| `/api/v1/runtime` | service health, stream diagnostics |
| `/api/auth` | login, register, profile, API keys, workspace, invites, roles, `/config` (unauthenticated) |
| `/api/v1/insight` | experiment analytics (analytics switch; `/api/v1/ee/insight` is a deprecated alias) |
| `/api/v1/event` | event log from ClickHouse (analytics switch; `/api/v1/ee/event` is a deprecated alias) |
| `/api/v1/ee/billing` | Stripe billing (cloud edition) |

### Request flow

1. **Create pool**: proxy → Postgres
2. **Create experiment**: proxy → Postgres → Redis
3. **Select**: client → proxy (auth, gates) → motor → Redis (cached params)
4. **Feedback**: client → proxy → Redis Streams → cortex (batch train) → Redis
5. **Analytics**: trace consumes the streams → ClickHouse → insight/event routes

## Frontend

`web/` is a pnpm workspace: the console, a Next.js 15 app (App Router, TypeScript), and
a shared UI package.

- **console** (`web/apps/console`, port 3001): the app. `output: standalone`. Calls
  the proxy same-origin at `/api` by default (`NEXT_PUBLIC_API_URL` overrides it at
  build time, for `next dev`). Uses @tanstack/react-query, recharts, date-fns,
  lucide-react.
- **@qbrix/ui** (`web/packages/ui`): design tokens in a Tailwind v4 `@theme` block
  (`src/styles/globals.css`, CSS-first, no `tailwind.config.ts`), Geist Sans and
  Geist Mono (`src/fonts.ts`), and shared components (logo, toast, skeleton,
  confirm dialog, error boundary).

`docs/*.mdx` is the user documentation, rendered at qbrix.io/docs by the marketing
site. The site lives in its own repository and reads `docs/` from `main` at build
time, so a docs merge redeploys it (`docs.yml`). Run `pnpm check-docs` in `web/`
before pushing a docs change: CI runs it, and it catches a page that won't compile,
bad frontmatter, or a `/docs/...` link or anchor that doesn't resolve.

### Console routes

| Route | Description |
|-------|-------------|
| `/dashboard` | metrics, service health, active experiments |
| `/experiments`, `/experiments/[id]` | experiment list and detail |
| `/experiments/[id]/insights`, `/activity` | analytics (a 404 when the deployment has no analytics) |
| `/experiments/[id]/gate` | the experiment's feature gate; gates have no id of their own, so there is no `/gates` route |
| `/pools` | pools |
| `/developers/event-log` | live event log (analytics) |
| `/settings` | profile, API keys, workspace, members, billing |
| `/invite` | invite acceptance |
| `/checkout`, `/billing/*`, `/onboarding/billing` | cloud edition only, in `src/app/(ee)` |

## Libraries

### qbrixcore (`lib/core`)

The bandit algorithms.

- **Stochastic:** BetaTS, DiscountedTS, GaussianTS, DirichletTS, UCB1Tuned, KLUCB,
  KLUCBPlus, Epsilon, MOSS, MOSSAnyTime, Random
- **Contextual:** LinUCB, GLMUCB, LinTS, LogisticTS
- **Adversarial:** EXP3, EXP3IX, FPL
- **Meta:** MetaBanditPolicy, which selects among learners

Key abstractions:
- `BasePolicy`: `name`, `select()`, `train()`, `init_params()`, `user_params()`, with
  `category` (`stochastic`, `contextual`, `adversarial`, `meta`) and
  `reward_types` (`RewardType.BINARY`, `BOUNDED`, `CONTINUOUS`).
- `PolicyParam`: metadata for user-configurable parameters.
- `BaseParamState` (pydantic) and `BaseParamBackend` (`InMemoryParamBackend`,
  `RedisParamBackend`).
- `Agent`, `Pool` / `Arm`, `Context`.
- `ContextSchema` / `ContextProperty`: the declared context shape (categorical,
  numeric, boolean). `encode()` turns named properties into the vector; `dim` is
  derived and capped at `MAX_CONTEXT_DIM`.

Policies register in `qbrixcore/policy/__init__.py` (`POLICIES`).

### qbrixstore (`lib/store`)

Postgres, Redis and ClickHouse.

**Postgres** (SQLAlchemy 2.0, asyncpg): `Tenant`, `User`, `APIKey`, `Invite`,
`Pool`, `Arm`, `Experiment`, `FeatureGate`, and the billing tables
(`StripeCustomer`, `Subscription`, `Invoice`), which stay in the one migration
chain and are unused outside the cloud edition. The schema is owned by Alembic
(`qbrixstore/migrations/`); services never create tables.

**Redis:** `RedisClient` for params and experiment caching;
`RedisStreamPublisher` / `RedisStreamConsumer` for the event streams. The consumer
is transport only, returning raw `(id, dict)` entries. `RedisSettings` carries the
connection only; which stream a publisher or consumer uses is passed explicitly.

**Stream topology** (`qbrixstore/stream/topology.py`):
- `StreamSpec` declares one stream: name, event type, consumer groups, `max_len`,
  per-group start ids. The registry (`FEEDBACK`, `SELECTION`, `AUDIT`) is the
  complete set.
- `delete_on_ack` is derived, never passed. `XDEL` on ack removes the entry for
  every group, so it is only safe with exactly one group; adding a group turns it
  off for all consumers. `FEEDBACK` overrides it explicitly.
- Joining a group not declared on the spec fails at construction.
- Stream names, groups and start positions are not configurable, because a
  publisher and consumer configured separately drift into silence rather than
  fail. Only `*_CONSUMER_NAME` (replica identity) is.

**Consumer loop** (`qbrixstore/stream/worker.py`): `StreamWorker` is the one loop
(connect → reclaim the PEL → read → batch → handler → ack) that cortex, trace and
meter all run on. Import it from `qbrixstore.stream.worker`; it is not re-exported
from `qbrixstore.stream`, to avoid an import cycle.
- The handler's return value decides the ack: return the ids to ack now, or `[]` to
  defer it (cortex until training completes, meter until Stripe accepts).
- `flush_interval_sec <= 0` hands over every non-empty read. `> 0` buffers to
  `batch_size` or the interval and then calls the handler even with an empty batch,
  so time-driven work can live there. Write-only handlers must guard on empty.
- A decode failure quarantines that entry (acked, logged with its payload,
  counted), not the batch. Only `EventDecodeError` is quarantined; anything else is
  a bug and goes to the retry loop.
- `stop()` drains the buffer through the handler and is the only way to stop a
  worker; never cancel its task.
- PEL recovery stops when it stops seeing new ids, not when `XAUTOCLAIM`'s cursor
  resets, since deferred acks keep entries pending.

**Events** (`qbrixstore/event/`): `FeedbackEvent`, `SelectionEvent`, `AuditEvent`.
The `Event` base derives encode and decode from the dataclass fields. Decoding is
tolerant (unknown keys ignored, absent optional fields defaulted) because publishers
and consumers deploy separately; an absent required field raises `EventDecodeError`.

**ClickHouse** (the `clickhouse` extra): client, event read/write, migrations. Not
re-exported from the package root, so motor, cortex and meter never load the driver.

### qbrixproto (`lib/proto`)

Generated gRPC stubs (`common`, `motor`, `proxy`, `cortex`, `auth`). Sources are in
`proto/`; regenerate with `make proto`. Never edit or format the stubs.

### qbrixlog (`lib/log`)

```python
from qbrixlog import configure_logging, get_logger, request_context

configure_logging("motorsvc")      # once, at startup
logger = get_logger(__name__)

with request_context("req-12345"):
    logger.info("processing request")
```

JSON output with `LOG_FORMAT=json`, text otherwise. Request ids propagate through
contextvars.

### qbrixruntime (`lib/runtime`)

How a service process starts, serves and stops, shared by all of them.

| Module | Provides |
|--------|----------|
| `shutdown.py` | `shutdown_signal()`: SIGTERM/SIGINT as an `asyncio.Event` |
| `grpc.py` | `build_server()`, `add_health()`, `enable_reflection()`, `bind()`, `serve_until_shutdown()` |
| `config.py` | `GrpcSettings`, inherited by every service's settings |
| `task.py` | `drain()`: cancel helper tasks and absorb their cancellation |

`serve_until_shutdown()` encodes constraints that are easy to break:
- The grpc server is stopped **before** its termination waiter is cancelled;
  cancelling `wait_for_termination()` on a running server kills teardown with a
  `CancelledError`.
- Signal handlers are installed **before** any library that manages its own.
  uvicorn restores whatever handler it displaced and re-raises the signal; with no
  handler of ours that is `SIG_DFL`, which kills the process mid-teardown.
- The health servicer's overall (`""`) entry goes to `NOT_SERVING` before draining,
  because that is the entry Kubernetes `grpc:` probes check.

Every service bounds its drain with `{SERVICE}_SHUTDOWN_GRACE_SEC` (default `20`).

## Roles and plans

| Role | Access |
|------|--------|
| admin | everything, including members, workspace settings and billing |
| member | all resource operations |
| viewer | read-only |

Plans exist only in the cloud edition, defined in
`svc/proxy/src/proxysvc/ee/plans.py` (`PLAN_LIMITS`, `FEATURE_MIN_TIER`). Request
rate is not tiered: a flat per-principal abuse guard (`ABUSE_RATE_LIMIT_PER_MINUTE`)
covers select and feedback on both transports. Invite emails are capped per
workspace per UTC day (`INVITES_PER_TENANT_PER_DAY`), counted on send, so
revoking and re-inviting cannot exceed it.

The unauthenticated auth endpoints (`login`, `register`, `refresh`,
`forgot-password`, `reset-password`) have their own Redis-backed pre-auth limiter,
per IP and, for login and forgot-password, per email, returning `429` with
`Retry-After`. The client IP is the `X-Forwarded-For` entry
`PROXY_TRUSTED_PROXY_HOPS` from the right (default `1`), or
`CloudFront-Viewer-Address` when `PROXY_TRUST_CLOUDFRONT_HEADER` is set
(`transport/http/auth/util.py`). The limits are constants in
`transport/http/auth/constant.py`, and are bypassed in dev mode.

## Tech stack

Python 3.10+ with uv workspaces; Postgres; Redis (params cache and streams);
cachebox; gRPC; FastAPI; ClickHouse (analytics); Stripe (cloud edition); Docker
Compose and Helm. Frontend: Next.js 15, TypeScript, Tailwind CSS v4, pnpm.

## Commands

```bash
make install                        # uv sync --all-packages
uv run pre-commit install           # black on commit, once per clone

uv run pytest                       # all tests (cloud edition on)
uv run pytest lib/core/tests        # one package
uv run pytest -k test_name          # one test
uv run pytest -m unit               # by marker: unit, integration, slow, performance
PROXY_EE_ENABLED=false uv run pytest svc/proxy   # self-hosted edition

make infra                          # postgres + redis (docker-compose.dev.yml)
make infra-ee                       # plus clickhouse
make dev                            # infra, migrations, then all services locally
make dev-proxy                      # or one service: dev-motor, dev-cortex, dev-trace

make docker                         # full stack in containers, built from source
make docker-ee                      # plus analytics and the cloud edition

make proto                          # regenerate gRPC stubs
make lint                           # black --check
make fmt                            # black
make migrate                        # alembic upgrade head against localhost
make db-reset                       # reset postgres and re-apply migrations
make loadtest                       # headless load test (60s)
```

Test config: `asyncio_mode = "auto"`, `--import-mode=importlib`,
`--strict-markers`. Tests substitute aiosqlite for Postgres, and the suite
conftest turns both edition switches on unless the environment sets them.

**Migrations:** after changing `lib/store/qbrixstore/postgres/models.py`:

```bash
cd lib/store && POSTGRES_HOST=localhost uv run alembic revision --autogenerate -m "describe change"
# review the file in qbrixstore/migrations/versions/, then
make migrate
```

The runner ships in the qbrixstore wheel (`python -m qbrixstore.migrate upgrade
head`), and the Helm chart runs it as a hook Job. A migration that drops a column
still being written must be split across two releases, because the hook runs
before the new code rolls out.

**Compose files:** `docker-compose.yml` is the self-host quickstart (published
images behind an nginx gateway on port 8000, secrets from `bin/selfhost-init`,
analytics as a profile). `docker-compose.dev.yml` builds from source and is what
every `make docker*` and `make infra*` target uses; its settings are in
`.env.dev.example`, with profiles `analytics`, `cloud` and `mail` (Mailpit).

**Helm:** `helm/qbrix` defaults to the self-host shape (GHCR images, in-cluster
Postgres and Redis, EE and analytics off, generated secrets). `bin/check-chart`
lints and renders it the way CI does. See `helm/README.md`.

## Conventions

### Logging

Log messages are lowercase.

```python
logger.info("starting motor service on port 50051")   # good
logger.info("Starting motor service on port 50051")   # bad
```

### Comments

Rare, lowercase, and never stating the obvious. A comment explains a constraint
the code cannot show; rationale for a change belongs in the commit message.

### Imports

One imported name per line; standard library, third party, then local; absolute
imports for local modules.

```python
from qbrixcore.policy.ts import BetaTSPolicy
from qbrixcore.policy.ucb import UCB1TunedPolicy
from qbrixcore.agent import Agent
```

### Types and async

Type hints on every signature, with `from __future__ import annotations` for
forward references. Prefer async I/O, use `asyncio.gather` for concurrency, and
never block the event loop.

### Versions and releases

The product has one version, written in every `pyproject.toml`, `Chart.yaml` and
web `package.json`. release-please bumps all of them in its release PR
(`.github/workflows/release.yml`); never edit them by hand. PR titles are
conventional commits, enforced by `pr-title.yml`, because the squashed title is the
release-note line. Base images, compose and chart infrastructure images are pinned
by digest and actions by commit SHA; Dependabot keeps both current with minor and
patch updates. `bin/check-chart` holds the chart's infrastructure images equal to
compose's, since Dependabot cannot update the chart.

### Dependencies

Always uv, never pip:

```bash
uv add <package> --package <package-name>
uv add --dev <package>
uv sync --all-packages
```

## Configuration

Every service reads `{SERVICE}_*` environment variables (`PROXY_`, `MOTOR_`,
`CORTEX_`, `TRACE_`, `METER_`); the settings classes in each service's `config.py`
are the reference. The ones that change behaviour most:

| Variable | Effect |
|----------|--------|
| `PROXY_RUNENV` | `dev` bypasses auth (default `dev`) |
| `PROXY_EE_ENABLED` | cloud edition (default `false`) |
| `PROXY_ANALYTICS_ENABLED` | analytics routes and streams (default `false`) |
| `PROXY_SIGNUP_MODE` | `open`, `first-user` (default) or `invite-only` |
| `PROXY_EMAIL_PROVIDER` | `auto` (default), `resend`, `smtp` or `none`; with no provider, new accounts are auto-verified |
| `PROXY_CONSOLE_URL` | the console origin used in email links |
| `PROXY_CORS_ORIGINS` | browser origins beyond the localhost defaults |
| `PROXY_TRUSTED_PROXY_HOPS`, `PROXY_TRUST_CLOUDFRONT_HEADER` | how the pre-auth limiter finds the client IP |
| `{SERVICE}_SHUTDOWN_GRACE_SEC` | drain budget on shutdown (default `20`) |
| `*_CONSUMER_NAME` | stream consumer identity; must differ per replica |
| `LOG_FORMAT`, `{SERVICE}_LOG_LEVEL`, `LOG_LEVEL` | logging |
