FROM python:3.10.16-slim as builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ARG UV_INDEX_ENVELOPE_USERNAME
ARG UV_INDEX_ENVELOPE_PASSWORD

ENV UV_INDEX_ENVELOPE_USERNAME=${UV_INDEX_ENVELOPE_USERNAME}
ENV UV_INDEX_ENVELOPE_PASSWORD=${UV_INDEX_ENVELOPE_PASSWORD}

RUN apt-get update && apt-get install -y --no-install-recommends build-essential git && apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*
RUN pip install uv

WORKDIR /app
COPY svc/cortex/pyproject.toml svc/cortex/uv.lock svc/cortex/README.md ./
RUN uv sync --frozen --no-editable

FROM python:3.10.16-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ARG UV_INDEX_ENVELOPE_USERNAME
ARG UV_INDEX_ENVELOPE_PASSWORD

ENV UV_INDEX_ENVELOPE_USERNAME=${UV_INDEX_ENVELOPE_USERNAME}
ENV UV_INDEX_ENVELOPE_PASSWORD=${UV_INDEX_ENVELOPE_PASSWORD}

RUN apt-get update && apt-get install -y --no-install-recommends curl git && apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*
RUN curl -sSL https://github.com/fullstorydev/grpcurl/releases/download/v1.9.1/grpcurl_1.9.1_linux_x86_64.tar.gz | tar -xz -C /usr/local/bin
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app
RUN pip install uv
COPY --from=builder /app /app
COPY svc/cortex/src/ ./src/
COPY svc/cortex/pyproject.toml ./

RUN mkdir -p /home/appuser/.cache/uv && chown -R appuser:appuser /home/appuser
RUN chown -R appuser:appuser /app
RUN uv pip install --no-cache-dir -e . --system

USER appuser

EXPOSE 50052

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD grpcurl -plaintext localhost:50052 qbrix.cortex.CortexService/Health || exit 1

CMD ["server"]
