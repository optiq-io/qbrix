# Contributing to qbrix

Thanks for your interest. Bug reports, fixes, docs and new policies are all welcome.

## Before you start

- **Bugs:** open an issue with steps to reproduce, what you expected, and what
  happened. Include versions and whether analytics is on.
- **Features and larger changes:** open an issue first, so we can agree on the
  approach before you spend time on it.
- **Security issues:** don't open an issue. Follow [`SECURITY.md`](SECURITY.md).

## Development setup

You need Python 3.10+, [uv](https://github.com/astral-sh/uv), Docker, and for the
console, Node.js 22 with [pnpm](https://pnpm.io).

```bash
make install                  # uv sync --all-packages
uv run pre-commit install     # black on every commit

make dev                      # postgres + redis in docker, migrations, then proxy, motor and cortex locally
```

`make dev` runs the proxy with `PROXY_RUNENV=dev`, which bypasses auth with a seeded
user, so you can call the API without a token on <http://localhost:8080>. It serves
a synthetic user, so anything that depends on a real user or tenant needs the proxy
restarted without it.

To run the whole stack in containers, built from your checkout:

```bash
make docker                   # core services and the console
make docker-ee                # plus analytics (trace, clickhouse) and the cloud edition
```

Settings for that stack are in `.env.dev.example`.

The console:

```bash
cd web
pnpm install
pnpm dev:console              # http://localhost:3001
```

## Tests

```bash
uv run pytest                                   # everything, cloud edition on
uv run pytest lib/core/tests                    # one package
uv run pytest -k test_name                      # one test
PROXY_EE_ENABLED=false uv run pytest svc/proxy  # the self-hosted edition
```

CI runs the suite twice: once as is, and once with every path in
`bin/ee-paths.txt` deleted and `PROXY_EE_ENABLED=false`. A change that passes the
first and fails the second has made core depend on the cloud edition.

For console changes:

```bash
cd web
pnpm --filter @qbrix/console check-boundary
pnpm --filter @qbrix/console type-check
pnpm --filter @qbrix/console build
```

For chart changes, run `bin/check-chart`.

## Where code goes

qbrix is open core. The cloud edition (billing, plan tiers, the usage meter) lives
in `ee` directories next to the code they extend, listed in `bin/ee-paths.txt`.

- Core never imports cloud code directly. In the proxy, only
  `svc/proxy/src/proxysvc/edition.py` may import `proxysvc.ee`. In the console,
  only `src/lib/edition.ts` may import `src/ee` or `src/app/(ee)`. The console
  build enforces its boundary.
- Anything a self-hosted install needs belongs in core.
- If you add an `ee` directory, add it to `bin/ee-paths.txt`. CI fails if a listed
  path is missing.

## Conventions

- **Formatting:** black for Python (`make fmt`, `make lint`). Generated protobuf
  stubs are excluded; regenerate them with `make proto`.
- **Log messages** are lowercase: `logger.info("starting motor service")`.
- **Comments** are rare and lowercase. Explain a constraint the code can't show,
  and leave the rest to the code and the commit message.
- **Imports:** one imported name per line, grouped standard library, third party,
  local, with absolute imports for local modules.
- **Types:** type hints on every signature.
- **Async:** never block the event loop; use `asyncio.gather` for concurrent I/O.
- **Dependencies:** `uv add <package> --package <package-name>`, never pip.
- **Schema changes:** add an Alembic revision (`lib/store/qbrixstore/migrations/`).
  Services don't create tables at startup.

[`AGENTS.md`](AGENTS.md) has the architecture and the reasoning behind the main
design choices.

## Pull requests

- Keep a pull request to one change, with tests that pin its behaviour.
- Give it a [conventional commit](https://www.conventionalcommits.org/) title,
  e.g. `fix(proxy): ...` or `feat(core): ...`. Pull requests are squash-merged, so
  the title becomes the commit on `main` and the line in the release notes; a CI
  check rejects any other shape. `feat`, `fix` and `perf` appear in the notes, and
  a `!` after the type or scope marks a breaking change.
- Describe what changed and why, and how you verified it.
- CI must be green.

## Releases

Releases are cut by [release-please](https://github.com/googleapis/release-please).
It keeps one `chore: release X.Y.Z` pull request open, updated on every merge to
`main`, which bumps the single product version everywhere it appears and collects
the release notes. Merging it tags `vX.Y.Z`, which publishes the images and the
Helm chart, and opens a draft GitHub Release that a maintainer edits and publishes.
Don't bump versions by hand.

## License

qbrix has no CLA. By contributing, you agree that your contribution is licensed
under the license of the files it changes: [Apache-2.0](LICENSE) for core, or the
[qbrix Enterprise License](ee/LICENSE) for the paths in `bin/ee-paths.txt`.

## Support

GitHub issues are the support channel for self-hosted qbrix, answered on a
best-effort basis with no response-time commitment. For managed hosting or a
support agreement, write to [info@optiqio.com](mailto:info@optiqio.com).
