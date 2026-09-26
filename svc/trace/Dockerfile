FROM python:3.10.21-slim-bookworm@sha256:2559be987fd64d61badbdafd303ea58a9ccab36d6c3c08bce219e762177d2eca AS builder

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

# copy service
COPY svc/trace svc/trace

# install dependencies
RUN uv sync --frozen --no-dev --no-editable --package tracesvc

FROM python:3.10.21-slim-bookworm@sha256:2559be987fd64d61badbdafd303ea58a9ccab36d6c3c08bce219e762177d2eca

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m pip uninstall --yes pip setuptools wheel
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# copy virtual environment from builder
COPY --from=builder /workspace/.venv /app/.venv

# copy service source
COPY svc/trace/src ./src

ENV PATH="/app/.venv/bin:$PATH"

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 50053

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["python", "-m", "qbrixruntime.probe", "localhost:50053"]

CMD ["python", "-m", "tracesvc.cli"]
