# Qbrix Frontend Deployment

## Overview

The qbrix frontend is a pnpm workspace (`web/`) containing the console, a Next.js application, and a shared UI package. The marketing site (qbrix.io) is built and deployed from its own repository, and renders this repository's `docs/` at build time.

```
web/
  pnpm-workspace.yaml
  packages/
    ui/               @qbrix/ui — shared components, styles, fonts, utils
  apps/
    console/          @qbrix/console — app console (cloud.qbrix.io)
```

## Applications

### console (App Console)

| Property | Value |
|---|---|
| **Domain** | `cloud.qbrix.io` |
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
                    Internet
                       │
          ┌────────────┼────────────┐
          │                         │
          ▼                         ▼
    ┌───────────┐            ┌─────────────┐
    │  qbrix.io │            │cloud.qbrix.io│
    │   (www)   │            │   (cloud)    │
    │  Static   │            │  Next.js SSR │
    │  S3+CDN   │            │    on EKS    │
    └───────────┘            └──────┬───────┘
                                    │ /api (same origin)
                                    ▼
                             ┌─────────────┐
                             │  proxysvc   │
                             │  HTTP :8080 │
                             └──────┬──────┘
                                    │ gRPC
                        ┌───────────┼───────────┐
                        ▼           ▼           ▼
                    motorsvc    cortexsvc     Redis
```

### User flow

1. User visits `qbrix.io` → sees marketing homepage (static, CDN-served)
2. Clicks "Get Started" or "Log in" → redirects to `cloud.qbrix.io/login`
3. Authenticates against proxysvc → JWT tokens stored client-side
4. Lands on `cloud.qbrix.io/dashboard` → all API calls go to proxysvc

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

### Production (AWS EKS + CloudFront)

**console (app):**
- Build Docker image from `web/apps/console/Dockerfile` (context: `web/`)
- Deploy to EKS as a Kubernetes Deployment + Service
- Helm subchart at `helm/qbrix/charts/console/`
- Sits behind the same ALB/Ingress as proxysvc
- CloudFront CDN in front with `cloud.qbrix.io` custom domain
- ACM certificate for `cloud.qbrix.io`
- Built with no API build arg: the console calls `/api` on its own host, and the ingress routes `/api` to proxysvc

**DNS (Route53):**
- `qbrix.io` → CloudFront distribution (www static)
- `cloud.qbrix.io` → CloudFront distribution (console app on EKS origin)

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

## Helm Chart Integration

The console app should be added as a subchart under `helm/qbrix/charts/console/`:

```
helm/qbrix/charts/
  proxy/          # HPA enabled
  motor/          # HPA enabled
  cortex/         # single instance
  console/        # HPA enabled (new)
```

Key Helm values for the cloud subchart:

```yaml
console:
  replicaCount: 2
  image:
    repository: <ecr-registry>/qbrix-console
    tag: latest
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
```

## Terraform Resources Needed

For the IAC engineer, these AWS resources are required:

### S3 + CloudFront (www)
- S3 bucket for static site hosting
- CloudFront distribution with S3 origin
- ACM certificate for `qbrix.io`
- Route53 A record → CloudFront

### CloudFront + ALB origin (cloud)
- CloudFront distribution with ALB origin (EKS ingress)
- ACM certificate for `cloud.qbrix.io`
- Route53 A record → CloudFront
- Cache behavior: bypass cache for all paths (dynamic app)

### ECR
- ECR repository for `qbrix-console` image

### CI/CD considerations
- www: built, uploaded to S3 and invalidated from its own repository
- console: build Docker image → push to ECR → update EKS deployment
