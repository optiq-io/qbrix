# Qbrix Frontend Deployment

## Overview

The qbrix frontend is a pnpm workspace (`web/`) containing the console, a Next.js application, and a shared UI package. The marketing site (qbrix.io) is built and deployed from its own repository, and renders this repository's `docs/` at build time.

```
web/
  pnpm-workspace.yaml
  packages/
    ui/               @qbrix/ui — shared components, styles, fonts, utils
  apps/
    console/          @qbrix/console — app console
```

## Applications

### console (App Console)

| Property | Value |
|---|---|
| **Purpose** | Login, register, dashboard, experiments, pools, settings |
| **Next.js output** | `standalone` (Node.js server) |
| **Docker image** | `qbrix-console` — Node.js standalone server |
| **Auth** | JWT tokens via proxysvc |
| **API calls** | All requests go to proxysvc HTTP API |
| **Port** | 3000 |

The console app is the EE (Enterprise Edition) web console. It authenticates users against proxysvc and provides the management UI for experiments, pools, and settings.

**Environment variables:**

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `/api` (same origin) | proxysvc HTTP API base URL. Inlined at build time, so leave it unset for an image meant to run on any host; set it only when console and proxy are different origins (`next dev`, the compose stack) |

## Architecture

```
                  Browser
                     │
                     ▼
            ┌─────────────────┐
            │ gateway/ingress │
            └───┬─────────┬───┘
            /   │         │ /api
                ▼         ▼
        ┌────────────┐ ┌─────────────┐
        │  console   │ │  proxysvc   │
        │Next.js SSR │ │  HTTP :8080 │
        └────────────┘ └──────┬──────┘
                              │ gRPC
                  ┌───────────┼───────────┐
                  ▼           ▼           ▼
              motorsvc    cortexsvc     Redis
```

### User flow

1. User opens the console's `/login` on the deployment's host
2. Authenticates against proxysvc → JWT tokens stored client-side
3. Lands on `/dashboard` → all API calls go to proxysvc under `/api` on the same host

### Backend interaction

The console app communicates exclusively with **proxysvc** via its HTTP API (`/api/v1/*` and `/auth/*`). It does NOT call motorsvc or cortexsvc directly. All requests include a JWT `Authorization: Bearer <token>` header.

Key API paths:
- `POST /auth/login` — authenticate
- `POST /auth/register` — create account
- `POST /auth/refresh` — refresh JWT token
- `GET /api/v1/experiments` — list experiments
- `GET /api/v1/pools` — list pools
- `GET /api/v1/gates` — list feature gates
- `GET /api/v1/agents` — list agents

## Deployment Targets

### Kubernetes (Helm)

- The chart at `helm/qbrix/` deploys the console as a Deployment + Service (`helm/qbrix/charts/console/`), using the published image `ghcr.io/optiq-io/qbrix/console`
- With ingress enabled on both subcharts and a shared host, `/` routes to the console and `/api` to proxysvc
- The image is built with no API build arg, so it runs on any host
- Chart values and installation are in [`helm/README.md`](../helm/README.md)

### Local / Self-hosted (Docker Compose)

The self-host quickstart (`docker-compose.yml`) pulls the published console image and serves it behind a gateway on `http://localhost:8000`, with the api on the same origin under `/api`.

The contributor stack builds from source:

```bash
# full stack including the console on :3001
docker compose -f docker-compose.dev.yml up --build
```

## Docker Images

### qbrix-console

```dockerfile
# build: from web/ directory
docker build -f apps/console/Dockerfile -t qbrix-console .
```

Multi-stage build:
1. Install pnpm workspace dependencies
2. Build standalone server (`next build` with `output: "standalone"`)
3. Copy standalone output to minimal Node.js image

Final image: ~150MB (Node.js + standalone server)

## Shared UI Package (@qbrix/ui)

The console depends on `@qbrix/ui` (workspace dependency). It contains:
- Design tokens and global CSS (`src/styles/globals.css`)
- Font configuration (`src/fonts.ts`)
- Shared components: QbrixMark / QbrixBrick (logo), Toast, Skeleton, ConfirmDialog, ErrorBoundary
- Utility functions (`src/lib/utils.ts`)

This package is NOT published — it's consumed via pnpm workspace protocol (`workspace:*`). The console Dockerfile copies the package into the build context.
