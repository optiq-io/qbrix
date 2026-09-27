# GitHub Actions Workflows

## Secrets and variables

The test, lint and chart jobs need nothing. Only the jobs that publish do:

| Name | Kind | Used by |
|------|------|---------|
| `AWS_ACCOUNT_ID` | secret | `build.yml` (ECR push, via GitHub OIDC) |
| `DOCS_BRIDGE_APP_ID` | variable | `docs.yml` |
| `DOCS_BRIDGE_APP_PRIVATE_KEY` | secret | `docs.yml` |
| `RELEASE_APP_ID` | variable | `release.yml` |
| `RELEASE_APP_PRIVATE_KEY` | secret | `release.yml` |
| `CONSOLE_SENTRY_DSN` | variable | `build.yml` (console image) |

The GHCR publish uses the workflow's own `GITHUB_TOKEN`.

Every `uses:` is pinned to a full commit SHA, with the release it came from as a
trailing comment. Dependabot (`.github/dependabot.yml`) moves the SHA and the
comment together, once a week, alongside the Docker base images and the compose
images (pinned by digest) and the uv and npm lockfiles. It proposes minor and
patch updates only: a major version, Python past 3.10, and a new ClickHouse release
(its versions are year.month, so every "minor" is one) are deliberate changes with
their own ticket. Its titles are `ci: ...` and `build: ...`, so they pass the
title check.

Dependabot cannot update the chart's infrastructure images, so `bin/check-chart`
requires them to equal the ones compose pins. A compose bump fails the `helm` job
until the same image is set in `helm/qbrix/values.yaml`.

## Workflows

### `ci.yml` — Pull Request Checks

**`test`** — the reusable `_test.yml` suite (below).

**`web`** — installs the pnpm workspace once, then runs the console's edition
boundary check (`check-edition-boundary.mjs`: only `src/lib/edition.ts` may import
`src/ee` or `src/app/(ee)`), its type-check and build, and `pnpm check-docs`: every
`docs/*.mdx` page compiles as MDX, carries the frontmatter the site reads, and every
`/docs/...` link and anchor resolves.
The console is a single build for both editions — the edition arrives at runtime
from the backend — so there is nothing to matrix here. It runs on PRs only: no
image waits on it.

**`helm`** — `bin/check-chart`, which runs locally the same way. It lints and
renders `helm/qbrix` under the release name `staging` for the defaults, both
examples, and everything switched on. Every bare `*_HOST` in the render must name
a Service in the same render, and every secret or configmap a pod references must
exist there with the key it reads. It also asserts that an explicit host still
wins and that a missing external host fails the render, and that the chart's
Postgres, Redis and ClickHouse images are the ones compose pins. It is not path-filtered,
because it takes seconds and a filtered check is one a chart-only PR can skip.

### `build.yml` — Docker Images (ECR + GHCR)

Builds and pushes container images: the private ECR images the cloud deploys,
and the public GHCR images and chart. Builds are **scoped to changed services**,
so a one-service change does not rebuild every image. Jobs run as
`detect → test → build / publish → retag / chart → gate`.

Both pushes are **gated on the python suite passing**. The suite lives in the
reusable `_test.yml` workflow; on push to main / `v*` tags `build.yml` runs it as
the `test` job and the build/push only proceeds if it succeeds. On Pull Requests
the same suite runs via `ci.yml` (the required status check) and the `test` job
here is skipped, so tests run once per event — never twice.

**`detect`** — maps changed paths to affected services and emits a dynamic
build matrix. Because every python service Dockerfile bundles the shared libs,
a change to `lib/**`, `proto/**`, `pyproject.toml`, or `uv.lock` fans out to all
of them (proxy, motor, cortex, trace); a service-only change builds just that
service. Path → service map:

| Change in… | Builds |
|---|---|
| `lib/**`, `proto/**`, `pyproject.toml`, `uv.lock` | proxy, motor, cortex, trace |
| `svc/proxy/**` / `svc/motor/**` / `svc/cortex/**` / `svc/trace/**` | that service |
| `ee/svc/meter/**` | meter |
| `web/apps/console/**`, `web/packages/**`, `web/pnpm-lock.yaml` | console |

**`test`** (push only) — runs the reusable `_test.yml` suite. A failure skips
`build`, so no image is pushed.

**`build`** — matrix over changed services only.
- **On Pull Request:** builds to verify (`load`), does NOT push to ECR, then
  scans the image with Trivy and fails on any CRITICAL or HIGH finding that has a
  fix available. Unfixable findings are not a PR's to clear; the weekly scan
  reports them.
- **On Push to main / `v*` tag:** builds and pushes. Tags pushed:
  `sha-<short-sha>`, `main`, and semver (`v1.2.3`, `1.2`) on tags.
- Release tags (`v*`) always build and push all services.

**`retag`** (push to main only) — for services that did NOT build, copies their
current `main` image to the new `sha-<short-sha>` tag via a registry-side
manifest copy (no rebuild, no pull). This guarantees every service has an image
at every sha, so a deploy can pin all services to one tag.

**`publish`** (push only) — multi-arch (`amd64`, `arm64`) images at
`ghcr.io/optiq-io/qbrix/<svc>` for the changed services, meter excluded. `main`
pushes `:edge`; a `v*` tag pushes `X.Y.Z` and `X.Y` (and `:latest` for a final
release) for every service. The console is built without build args.
Each platform builds on its own native runner (`ubuntu-24.04`, `ubuntu-24.04-arm`)
in `publish-image` and is pushed by digest; `publish` joins the digests into one
manifest list, tags it, and attests it.
Each image carries a max-mode provenance attestation and an SBOM in its manifest,
and, once the repository is public, a GitHub artifact attestation, so a
self-hoster can check where an image was built:

```bash
gh attestation verify oci://ghcr.io/optiq-io/qbrix/proxy:0.1.0 -R optiq-io/qbrix
```

GitHub issues artifact attestations for private repositories only on Enterprise
plans, so that step is skipped while the repository is private.

**`chart`** (`v*` tags only) — checks that the umbrella chart and every subchart
carry the tag's version as both `version` and `appVersion`, then pushes
`oci://ghcr.io/optiq-io/charts/qbrix`. release-please bumps the charts in the
release commit; the check fails the release if one was missed, because a
subchart's image tag defaults to its `appVersion`.

**`gate`** — always-run aggregation job. Mark **this** as the required status
check in branch protection; skipped matrix jobs (nothing changed) won't wedge
the rules.

**ECR repositories required:** `qbrix/proxy`, `qbrix/motor`, `qbrix/cortex`, `qbrix/trace`, `qbrix/console`

> Note: the `retag` step assumes each service already has a `main` tag in ECR
> (true after the first full build). If a service has no `main` tag it is
> skipped with a warning; force a full rebuild by touching a shared path.

### `release.yml` — Releases

[release-please](https://github.com/googleapis/release-please) keeps one standing
release PR (`chore: release X.Y.Z`) open against `main`, rewritten on every push.
Its notes come from the conventional-commit titles merged since the last release,
grouped into features, fixes, performance and reverts; `chore`, `docs`, `ci`, `build`,
`test` and `refactor` stay out of the notes. The PR bumps the one product version
everywhere it is written: every `pyproject.toml` (the `# x-release-please-version`
lines), every `Chart.yaml` (`version`, `appVersion` and the umbrella's dependency
versions), the web `package.json` files, `CHANGELOG.md` and
`.release-please-manifest.json`. A second commit relocks `uv.lock`, which records
the workspace packages' versions.

release-please rewrites each versioned file from the contents it read when its run
started, so a PR merged while a run is in flight can be silently reverted in the
release PR, and later runs leave that branch alone while the notes are unchanged.
`ci.yml`'s `release-pr` job (`bin/check-release-pr`) fails the release PR if it
changes anything but the notes, the manifest, `uv.lock` and version lines. When it
fails, close the release PR and delete its branch; the next run on `main` reopens
it from the current tree.

Merging the release PR creates the `vX.Y.Z` tag and a **draft** GitHub Release with
the generated notes. The tag starts `build.yml`, which publishes the images and the
chart; the draft stays unpublished until someone rewrites the notes and publishes
it. Versions are `0.x` for now, so a `feat` bumps the minor version and a breaking
change bumps it too, rather than going to `1.0.0`.

Every write goes through a token minted from the release GitHub App
(`RELEASE_APP_ID`, `RELEASE_APP_PRIVATE_KEY`), narrowed to `contents` and
`pull-requests` write. A tag pushed with the workflow's own `GITHUB_TOKEN` starts no
other workflow, so with that token `build.yml` would never publish a release.

To choose a version instead of the computed one, end a squash commit's message with
a `Release-As: X.Y.Z` footer. The commit must still be user facing (`feat`, `fix`,
`perf`, `revert` or `deps`): release-please opens no release PR while the changelog
would be empty.

### `pr-title.yml` — PR Title

Pull requests are squash-merged, so the PR title becomes the commit on `main` and
the line in the release notes. This check fails a title that is not a
[conventional commit](https://www.conventionalcommits.org/): `type(scope): subject`,
with `type` one of `feat`, `fix`, `perf`, `refactor`, `docs`, `test`, `build`,
`ci`, `chore`, `revert` or `style`, and `!` after the type or scope for a breaking
change. It reruns when the title is edited.

### `scan.yml` — Image Scan

Every Monday, and on demand, Trivy rescans the published `:latest` and `:edge`
images of every public service against the current vulnerability database and
uploads the CRITICAL and HIGH findings, fixable or not, to code scanning. A release
that shipped clean does not stay clean. Code scanning on a private repository
needs GitHub Advanced Security, so the scan runs only once the repository is
public.

### `_test.yml` — Test Suite (reusable)

Called by `ci.yml` on every Pull Request and by `build.yml` on every push to main
or `v*` tag, where it gates both image pushes. It holds only what an image push
must wait on:

**`pytest`** — a matrix over the two editions, with Postgres + Redis services.

| Edition | What runs |
|---|---|
| `cloud` | `PROXY_EE_ENABLED=true`, the whole tree, with coverage uploaded to Codecov |
| `oss` | every path in `bin/ee-paths.txt` deleted, then `PROXY_EE_ENABLED=false` |

The `oss` run is what keeps the open-core boundary honest. Deleting the plugin is
stricter than switching it off: core that imports from `ee` fails on the push that
introduces it, rather than at a self-hoster's first install. The step fails if a
listed path is missing, so the list cannot rot after a move — and the same list is
named by the root LICENSE, so the licensed paths and the tested paths are one
statement.

`uv sync` runs without `--frozen` here, because the lockfile still names `metersvc`
and the oss tree no longer has it.

### `docs.yml` — Docs Redeploy

qbrix.io is built in a separate repository that reads `docs/` from this one at build
time. A push to `main` that touches `docs/**` mints a token from the docs bridge
GitHub App, narrowed to `actions: write` on that repository, and dispatches its
deploy workflow. It runs on push only, never on `pull_request`, so no fork can reach
the key. The site also rebuilds nightly, which covers a dispatch that fails.
