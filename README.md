<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./asset/logo/svg/lockup-dark.svg">
    <img src="./asset/logo/svg/lockup.svg" alt="qbrix" width="240">
  </picture>
</p>

<p align="center">
  <strong>Adaptive experiments that shift traffic to what works, while they run.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="License: Apache-2.0"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
</p>

---

qbrix is a self-hostable engine for multi-armed bandit experiments. You give it the
variants, it picks one per request, you report the outcome, and it moves traffic
toward the variants that perform. Use it where an A/B test would make you wait for
a winner: headlines, recommendations, pricing, onboarding flows, ranking.

Selection and learning are separate paths. Selection is a stateless, low-latency
service that scales horizontally; learning consumes feedback from a stream and
updates the model in the background, so training never slows a decision down.

## Features

- **19 policies**: Thompson sampling, UCB, KL-UCB, MOSS, epsilon-greedy, EXP3, FPL,
  contextual LinUCB / LinTS / GLM-UCB / logistic TS, and a meta-bandit that picks
  among them.
- **Contextual experiments**: declare a context schema and qbrix encodes named
  properties server-side.
- **Feature gates**: percentage rollouts and targeting rules in front of any
  experiment.
- **A console** for pools, experiments, gates, API keys and your team, with roles
  (admin, member, viewer).
- **Analytics** (optional): per-experiment insights and a live event log, backed by
  ClickHouse.
- **REST and gRPC** APIs, with [Python](https://github.com/optiq-io/qbrix-python) and
  [TypeScript](https://github.com/optiq-io/qbrix-js) SDKs.

## Quick start

You need Docker with Compose.

```bash
git clone https://github.com/optiq-io/qbrix.git && cd qbrix
bin/selfhost-init            # writes .env with generated secrets; add --analytics for insights
docker compose up -d
```

Open <http://localhost:8000> and register. The first account creates the workspace
and becomes its admin; after that, people join by invite. Create an API key under
**Settings → API keys**, then run an experiment from Python:

```bash
pip install "qbrix[http]"
export QBRIX_BASE_URL=http://localhost:8000
export QBRIX_API_KEY=optiq_...
```

```python
import qbrix

pool = qbrix.pool.create(
    name="homepage-buttons",
    arms=[{"name": "blue"}, {"name": "green"}, {"name": "red"}],
)
exp = qbrix.experiment.create(
    name="button-color", pool_id=pool.id, policy="BetaTSPolicy"
)

result = qbrix.agent.select(experiment_id=exp.id, context={"id": "user-123"})
print(result.arm.name)

# once you know whether it worked
qbrix.agent.feedback(request_id=result.request_id, reward=1.0)
```

`.env.example` documents every compose setting: port, email (SMTP), signup mode,
and analytics.

### Kubernetes

```bash
helm install qbrix oci://ghcr.io/optiq-io/charts/qbrix \
  -f https://raw.githubusercontent.com/optiq-io/qbrix/main/helm/qbrix/examples/values-selfhost.yaml
```

See [`helm/README.md`](helm/README.md) for routing, secrets, external databases,
analytics and upgrades.

## Architecture

| Service | Role |
|---------|------|
| **proxy** | REST and gRPC API, auth, experiments, pools, gates; publishes feedback |
| **motor** | selection: reads model parameters from Redis and picks an arm |
| **cortex** | learning: consumes feedback from Redis Streams and trains |
| **trace** | analytics (optional): writes the event streams to ClickHouse |
| **console** | the web app |

Postgres holds experiments, pools and users; Redis holds model parameters and the
event streams.

## Editions

This repository is the whole product. Self-hosted, it has no usage limits, seat
caps or license keys.

The same code also runs **qbrix cloud**, our managed service. Its billing and plan
code lives in the `ee` directories listed in [`bin/ee-paths.txt`](bin/ee-paths.txt).
That code is off unless `PROXY_EE_ENABLED` is set, and CI proves on every push that
the product runs with those directories deleted. If you'd rather not operate qbrix
yourself, write to [info@optiqio.com](mailto:info@optiqio.com) about managed hosting.

## Contributing

Issues and pull requests are welcome. [`CONTRIBUTING.md`](CONTRIBUTING.md) covers
the development setup, tests and conventions. Report security issues privately, as
described in [`SECURITY.md`](SECURITY.md).

## License

The core is licensed under [Apache-2.0](LICENSE). The content under the paths listed
in [`bin/ee-paths.txt`](bin/ee-paths.txt) is licensed under the
[qbrix Enterprise License](ee/LICENSE). The qbrix name and logo are trademarks of
Optiq B.V.; see [`TRADEMARKS.md`](TRADEMARKS.md).
