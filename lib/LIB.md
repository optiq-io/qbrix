# Libraries

Shared libraries consumed by qbrix services. Each is an independent package managed via uv workspace. No cross dependencies.

## qbrixcore (`lib/core`)

Core multi-armed bandit algorithms and abstractions. Provides policies (Thompson Sampling, UCB, Epsilon-Greedy, LinUCB, EXP3, etc.), the `Agent` orchestrator, and param state/backend interfaces. No infrastructure dependencies — pure algorithmic logic.

## qbrixstore (`lib/store`)

Storage layer for Postgres and Redis. Includes SQLAlchemy 2.0 models (experiments, pools, arms, feature gates, users, API keys), async session management, Redis param caching, and Redis Streams publisher/consumer for the feedback queue.

## qbrixproto (`lib/proto`)

Generated gRPC/protobuf stubs for inter-service communication. Covers motor, proxy, cortex, and auth service definitions. Generated from `proto/` via `buf generate`.

## qbrixlog (`lib/log`)

Opinionated logging for all services. Provides `configure_logging()`, `get_logger()`, and a `request_context()` context manager for request ID propagation. Zero external dependencies.