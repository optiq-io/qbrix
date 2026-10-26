# qbrix Helm chart

Runs qbrix on Kubernetes: the proxy (API gateway), motor (selection), cortex (training), trace (the analytics writer) and the console, with in-cluster Postgres, Redis and ClickHouse by default.

For a single machine, the Docker Compose quickstart at the repository root is simpler.

## Install

Requirements: Kubernetes 1.25+, Helm 3.10+, an ingress controller (the examples use ingress-nginx) and a default StorageClass for the in-cluster databases.

```bash
curl -fsSL -o values.yaml https://raw.githubusercontent.com/optiq-io/qbrix/main/helm/qbrix/examples/values-selfhost.yaml
# edit the host (qbrix.example.com) in values.yaml, then
helm install qbrix oci://ghcr.io/optiq-io/charts/qbrix -f values.yaml
```

Any release name works. The in-cluster Postgres, Redis and ClickHouse services are named after the release (`<release>-postgres`, …), and the services find them there unless `global.*.host` points elsewhere.

Open the host in a browser and register. The first account creates the workspace and becomes its admin. After that, public registration closes and teammates join by invite from the console (`proxy.config.signupMode: first-user`).

From a checkout, `helm install qbrix ./helm/qbrix -f helm/qbrix/examples/values-selfhost.yaml` installs the same chart.

## Routing

The console calls the API on its own origin, under `/api`, so **both ingresses must serve the same host**:

| Path | Service |
|---|---|
| `/api` | proxy, port 8080 (`proxy.ingress`) |
| `/oauth`, `/.well-known/oauth-authorization-server` | proxy, port 8080 (`proxy.ingress`) |
| `/` | console, port 3000 (`console.ingress`) |

Email links (verification, password reset, invites) use `proxy.config.consoleUrl`. When that is unset they use the proxy ingress host, over `https` when `proxy.ingress.tls` is set.

## Secrets

With nothing configured, the chart generates the Postgres password, the JWT signing key and the selection-token secret on first install, and keeps them across upgrades. The Postgres secret also survives `helm uninstall`, because the database volume does.

Generated values are read back from the cluster, which render-only tools cannot do: `helm template`, Argo CD and Flux would get fresh values on every render. For those, or to manage secrets yourself, create them and name them:

| Value | Keys |
|---|---|
| `global.postgres.existingSecret` | `username`, `password` |
| `global.redis.existingSecret` | `password` |
| `global.clickhouse.existingSecret` | `password` |
| `proxy.config.jwt.existingSecret` | `jwt-secret` |
| `proxy.config.token.existingSecret` | `token-secret` |
| `proxy.config.smtp.existingSecret` | `smtp-password` |

## External databases

For anything beyond a single-node install, point the chart at managed Postgres, Redis and ClickHouse. `examples/values-external-services.yaml` shows how; layer it on top of the self-host values. With in-cluster Postgres disabled, a Postgres secret (or password) is required, and rendering fails without one.

Redis is not a cache here: it holds what every experiment has learned, and nothing else has a copy. Your own Redis must run `maxmemory-policy noeviction` with `appendonly yes` and `appendfsync everysec`, the settings the in-cluster one uses, and needs at least 1 GB of `maxmemory`, which the event streams are sized to fit. An eviction policy silently resets learning and takes experiments offline. When Redis is full, writes fail loudly instead, learning pauses, and selection keeps working.

## Email

Without an email provider, new accounts are verified automatically, and reset and invite links are written to the proxy log. To send mail, set `proxy.config.emailProvider: smtp`, `proxy.config.emailFrom` and `proxy.config.smtp.*`, with the SMTP password in `proxy.config.smtp.existingSecret`.

## Values

| Parameter | Description | Default |
|---|---|---|
| `global.imageRegistry` | Registry prefix; images are `<registry>/qbrix/<service>` | `ghcr.io/optiq-io` |
| `global.imageTag` | Image tag for every service (per service: `<svc>.image.tag`) | chart `appVersion` |
| `global.postgres.host` / `port` / `database` | Postgres connection; an empty host is the in-cluster service | `<release>-postgres` / `5432` / `qbrix` |
| `global.redis.host` / `port` | Redis connection; an empty host is the in-cluster service | `<release>-redis` / `6379` |
| `global.clickhouse.host` / `port` / `database` | ClickHouse connection, behind insights and the event log; an empty host is the in-cluster service | `<release>-clickhouse` / `8123` / `qbrix` |
| `global.logging.format` / `level` | `json` or `text` / log level | `json` / `WARNING` |
| `infrastructure.postgres.enabled` | In-cluster Postgres | `true` |
| `infrastructure.redis.enabled` | In-cluster Redis | `true` |
| `infrastructure.redis.maxmemory` | Redis memory ceiling; it never evicts, so keep it at 1gb or more and the memory limit above it | `1gb` |
| `infrastructure.clickhouse.enabled` | In-cluster ClickHouse | `true` |
| `trace.enabled` | Trace service, which writes the event streams to ClickHouse | `true` |
| `proxy.config.signupMode` | `first-user`, `invite-only` or `open` | `first-user` |
| `proxy.config.consoleUrl` | Public console URL for email links | the proxy ingress host |
| `proxy.config.corsOrigins` | Extra credentialed browser origins, comma separated | `""` |
| `proxy.config.trustedProxyHops` | Reverse proxies in front of the proxy that append to `X-Forwarded-For`; the login rate limit keys on the client address this many hops from the right | `1` |
| `proxy.config.trustCloudfrontHeader` | Key the login rate limit on `CloudFront-Viewer-Address`. Only for CloudFront origins whose request policy adds that header, since any other client can send it | `false` |
| `proxy.config.emailProvider` | `auto`, `smtp`, `resend` or `none` | `auto` |
| `<svc>.replicaCount`, `<svc>.autoscaling.*`, `<svc>.resources` | Sizing for proxy, motor, console, trace | see `charts/<svc>/values.yaml` |

`global.ee.enabled` and `ee.meter.enabled` switch on the cloud edition (plans, quotas, Stripe billing). A self-hosted install leaves them off.

## Scaling

| Service | Scaling | Why |
|---|---|---|
| proxy | horizontal | stateless gateway |
| motor | horizontal | stateless selection; the hot path |
| console | horizontal | stateless web app |
| trace | horizontal | append-only writes; replicas share one consumer group |
| cortex | **single instance** | training consumes feedback in order, so parameter updates are correct by construction; scale it vertically |

## Database migrations

The schema is managed by Alembic, and a hook Job runs `python -m qbrixstore.migrate upgrade head` with the proxy image:

- **on upgrade**, before the new pods roll out; a failed migration fails the upgrade
- **on first install**, right after the release's resources exist, once Postgres accepts connections

Set `proxy.migrations.enabled: false` to migrate out of band.

## Upgrade and uninstall

```bash
helm upgrade qbrix oci://ghcr.io/optiq-io/charts/qbrix --version <version> -f values.yaml
helm uninstall qbrix
kubectl delete pvc -l app.kubernetes.io/instance=qbrix   # deletes the data
kubectl delete secret qbrix-postgres                     # the kept, generated password
```
