FROM python:3.10.22-slim-bookworm@sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370 AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential && apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*
RUN pip install uv

WORKDIR /workspace

# copy workspace root files
COPY pyproject.toml uv.lock ./

# copy lib dependencies (required by tool.uv.sources)
COPY lib/core lib/core
COPY lib/store lib/store
COPY lib/proto lib/proto
COPY lib/log lib/log
COPY lib/runtime lib/runtime

# copy service
COPY svc/motor svc/motor

# install dependencies
RUN uv sync --frozen --no-dev --no-editable --package motorsvc

FROM python:3.10.22-slim-bookworm@sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m pip uninstall --yes pip setuptools wheel
# the pinned base trails debian's openssl security fix; drop once its digest carries it
RUN apt-get update && apt-get install -y --no-install-recommends --only-upgrade libssl3 openssl && apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# copy virtual environment from builder
COPY --from=builder /workspace/.venv /app/.venv

# copy service source
COPY svc/motor/src ./src

ENV PATH="/app/.venv/bin:$PATH"

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 50051

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["python", "-m", "qbrixruntime.probe", "localhost:50051"]

CMD ["python", "-m", "motorsvc.cli"]
