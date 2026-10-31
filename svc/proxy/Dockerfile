FROM python:3.14.10-slim-bookworm@sha256:516b51cb9db2ef061e465c803e50f64361b82cefd91e525b889b967b83e83527 AS builder

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
COPY lib/store lib/store
COPY lib/proto lib/proto
COPY lib/log lib/log
COPY lib/runtime lib/runtime
COPY lib/core lib/core

# copy service
COPY svc/proxy svc/proxy

# install dependencies
RUN uv sync --frozen --no-dev --no-editable --package proxysvc --extra ee --extra resend

FROM python:3.14.10-slim-bookworm@sha256:516b51cb9db2ef061e465c803e50f64361b82cefd91e525b889b967b83e83527

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m pip uninstall --yes pip setuptools wheel
# the pinned base trails debian's openssl security fix; drop once its digest carries it
RUN apt-get update && apt-get install -y --no-install-recommends --only-upgrade libssl3 openssl && apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY --from=builder /workspace/.venv /app/.venv

COPY svc/proxy/src ./src

ENV PATH="/app/.venv/bin:$PATH"

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 50050 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=5)"]

CMD ["python", "-m", "proxysvc.cli", "serve"]
