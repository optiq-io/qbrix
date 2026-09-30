# Qbrix Load Testing

Load testing suite for qbrix using [Locust](https://locust.io/).

## Behavior

- Experiments use **auto mode (meta-bandit)** by default
- Pass `--no-auto` to use random manual policies instead
- `--num-experiments` controls how many experiments to create (default: 1)
- Users are round-robin assigned across all experiments
- Realistic async feedback (70% of selections get feedback, with 100-2000ms delay)
- Probabilistic rewards (30% success rate)
- Select:Health request ratio is 10:1

## Usage

### Via Makefile

```bash
# 1 auto experiment, headless (60s, 10 users)
make loadtest

# web UI
make loadtest-web
```

### Via CLI

```bash
# 5 auto experiments, headless
cd bin && uv run python -m loadtest.cli -n 5 -u 50 -r 5 -t 60s

# 3 manual experiments with random policies
cd bin && uv run python -m loadtest.cli -n 3 --no-auto -u 30 -r 5 -t 60s

# web interface
cd bin && uv run python -m loadtest.cli -n 3 --web

# connect to a remote deployment
LOADTEST_API_KEY=optiq_xxx uv run python -m loadtest.cli -h qbrix.example.com -p 443 --scheme https --web
```

### CLI Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--num-experiments` | `-n` | `1` | Number of experiments to create |
| `--num-arms` | | `5` | Number of arms per pool |
| `--no-auto` | | `false` | Use random manual policies instead of auto |
| `--web` | | `false` | Start with web UI |
| `--host` | `-h` | `localhost` | Proxy service host |
| `--port` | `-p` | `8080` | Proxy service HTTP port |
| `--scheme` | | `http` | URL scheme: `http` or `https` |
| `--users` | `-u` | `10` | Number of concurrent users |
| `--spawn-rate` | `-r` | `1` | Users to spawn per second |
| `--run-time` | `-t` | | Run duration (e.g., `60s`, `5m`, `1h`) |
| `--web-host` | | `localhost` | Web UI host |
| `--web-port` | | `8089` | Web UI port |

## Configuration

All settings can be configured via environment variables with `LOADTEST_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `LOADTEST_PROXY_HOST` | `localhost` | Proxy service host |
| `LOADTEST_PROXY_PORT` | `8080` | Proxy service HTTP port |
| `LOADTEST_PROXY_SCHEME` | `http` | URL scheme |
| `LOADTEST_API_KEY` | | API key for authenticated requests |
| `LOADTEST_NUM_EXPERIMENTS` | `1` | Number of experiments |
| `LOADTEST_NUM_ARMS` | `5` | Number of arms per pool |
| `LOADTEST_AUTO` | `true` | Use auto (meta-bandit) mode |
| `LOADTEST_FEEDBACK_PROBABILITY` | `0.7` | Probability of sending feedback after select |
| `LOADTEST_FEEDBACK_DELAY_MIN_MS` | `100` | Min delay before sending feedback |
| `LOADTEST_FEEDBACK_DELAY_MAX_MS` | `2000` | Max delay before sending feedback |
| `LOADTEST_REWARD_SUCCESS_PROBABILITY` | `0.3` | Probability of positive reward |

## Prerequisites

Services must be running before load testing:

```bash
# start infrastructure and services
make dev

# in another terminal, run load tests
make loadtest-web
```

## Web Interface

When using `--web`, Locust starts a web interface at `http://localhost:8089` where you can:

- Configure number of users and spawn rate
- Start/stop tests
- View real-time charts (RPS, response times, failures)
- Download test results as CSV
