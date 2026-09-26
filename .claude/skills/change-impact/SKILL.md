---
name: change-impact
description: >
  Analyze the full impact of major backend or frontend changes across the qbrix system.
  Inspect all dependent areas (deployment, proto, tests, frontend, docs, CI/CD, repo docs),
  run tests, produce a structured impact report, and optionally delegate fixes to domain agents.
  Trigger when: (1) a significant BE change lands in lib/, svc/, or ee/svc/ that affects APIs,
  data models, config, or service behavior; (2) a major FE change in web/ that affects
  deployment or API contracts; (3) the user asks to assess change impact, run an impact
  analysis, or check what else needs updating after a change.
---

# Change Impact Analysis

Systematically inspect every area of the qbrix monorepo that may need updating after a major change. Produce a structured impact report, run tests, and offer to delegate fixes to domain agents.

## Workflow

### 1. Identify the Change

Determine what changed using:
- User description of the change
- `git diff main...HEAD` or `git diff --cached` for staged changes
- `git log --oneline main...HEAD` for commit history

Summarize in one sentence. Classify:
- **API change**: new/modified endpoints, proto messages, request/response shapes
- **Config change**: new env vars, service settings, feature flags
- **Data model change**: Postgres models, Redis key structures, param state
- **Service behavior change**: new service, changed scaling model, new dependencies
- **Frontend change**: new pages, API client changes, new UI features
- **Algorithm change**: new policy, changed training/selection logic

### 2. Inspect Impact Areas

For each area, inspect relevant files and determine if updates are needed. Use the Explore agent with codegraph tools for efficient lookups.

#### 2.1 Proto Definitions (`proto/`)
- Check if gRPC contracts need new messages, fields, or services
- Files: `proto/*.proto`, `proto/buf.yaml`, `proto/buf.gen.yaml`
- If changed: regenerate stubs with `make proto`, verify `lib/proto/` is updated

#### 2.2 Tests
- Run `uv run pytest` from project root
- Report pass/fail count, any failures with file paths
- Check if new test files are needed for new functionality
- Test locations: `lib/*/tests/`, `svc/*/tests/`, `ee/svc/*/tests/`

#### 2.3 Deployment — Helm (`helm/qbrix/`)
- Check if new env vars need chart values entries
- Files: `helm/qbrix/values.yaml`, `helm/qbrix/values-dev.yaml`
- Subchart templates: `helm/qbrix/charts/{proxy,motor,cortex,console,trace}/`
- Look for: new ConfigMap entries, ports, resource defaults, new subchart needed

#### 2.4 Deployment — Docker Compose (`docker-compose.yml`)
- Check for new environment variables, services, ports, volumes, healthchecks, profiles
- Check build context or Dockerfile path changes

#### 2.5 Environment Variables (`.env.example`)
- Cross-reference new env vars in service code with `.env.example`, docker-compose.yml, and helm values

#### 2.6 Makefile
- Check if new make targets are needed or existing targets need updating

#### 2.7 Load Testing (`bin/loadtest/`)
- Check if API changes affect loadtest scenarios
- Files: `bin/loadtest/scenarios/`, `bin/loadtest/client.py`, `bin/loadtest/config.py`

#### 2.8 Frontend — Console (`web/apps/console/`)
- Check if API contract changes require frontend updates
- Look for: API client functions, type definitions, pages consuming changed endpoints

#### 2.9 Documentation (`docs/`)
- Check `.mdx` files referencing changed APIs, config, or concepts
- Key: `docs/api-reference.mdx`, `docs/getting-started.mdx`, `docs/architecture.mdx`
- Run `pnpm check-docs` in `web/` after editing them

#### 2.10 CI/CD (`.github/workflows/`)
- Check workflows for new services, changed build steps, new test jobs
- Files: `ci.yml`, `build.yml`, `docs.yml`, `proto.yml`, `security.yml`

#### 2.11 Repo Documentation
- `README.md`: quick start, architecture table, algorithm table, deployment instructions
- `CLAUDE.md`: service descriptions, env var lists, project structure

### 3. Produce Impact Report

Output using this exact format:

```
## Impact Report: <one-line change summary>

### Change Classification
<type>

### Test Results
<pass/fail summary, failures with file paths>

### Impacted Areas

| Area | Status | Details |
|------|--------|---------|
| Proto | OK / NEEDS UPDATE | <what> |
| Tests | PASS / FAIL / NEEDS NEW | <what> |
| Helm | OK / NEEDS UPDATE | <what> |
| Docker Compose | OK / NEEDS UPDATE | <what> |
| .env.example | OK / NEEDS UPDATE | <what> |
| Makefile | OK / NEEDS UPDATE | <what> |
| Load Testing | OK / NEEDS UPDATE | <what> |
| Console (FE) | OK / NEEDS UPDATE | <what> |
| Docs | OK / NEEDS UPDATE | <what> |
| CI/CD | OK / NEEDS UPDATE | <what> |
| README | OK / NEEDS UPDATE | <what> |
| CLAUDE.md | OK / NEEDS UPDATE | <what> |

### Recommended Actions
<numbered list, ordered by priority>
```

### 4. Delegate to Domain Agents

After presenting the report, offer to fix impacted areas using domain agents:

| Area | Agent |
|------|-------|
| Proto, service code, Makefile, env vars | `backend-engineer` |
| Helm, Docker Compose, CI/CD | `backend-engineer` |
| Tests | `unit-test-writer` |
| Console frontend | `fe-engineer` |
| Architecture validation | `architecture-reviewer` |
| README, CLAUDE.md, docs/ | `backend-engineer` |

When delegating, provide the agent with:
1. The specific change that was made
2. The impact area findings from the report
3. Clear instructions on what to update

Run agents in parallel for independent areas when possible.
