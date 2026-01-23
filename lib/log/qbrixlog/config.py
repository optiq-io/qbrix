from __future__ import annotations

import logging
import os
import sys
from typing import Literal

from qbrixlog.formatters import JSONFormatter
from qbrixlog.formatters import TextFormatter

LogFormat = Literal["json", "text"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

_configured_services: set[str] = set()


def _get_log_level(service: str) -> int:
    """get log level from environment variable.

    checks SERVICE_LOG_LEVEL first (e.g., MOTOR_LOG_LEVEL),
    then falls back to LOG_LEVEL, then defaults to INFO.
    """
    service_env = f"{service.upper()}_LOG_LEVEL"
    level_str = os.environ.get(service_env) or os.environ.get("LOG_LEVEL", "INFO")
    return getattr(logging, level_str.upper(), logging.INFO)


def _get_log_format() -> LogFormat:
    """get log format from environment variable."""
    fmt = os.environ.get("LOG_FORMAT", "text").lower()
    return "json" if fmt == "json" else "text"


def configure_logging(
    service: str,
    level: LogLevel | None = None,
    log_format: LogFormat | None = None,
) -> None:
    """configure logging for a service.

    args:
        service: service name (e.g., "motorsvc", "proxysvc", "cortexsvc")
        level: log level override. if not provided, reads from env var.
        log_format: format override. if not provided, reads from env var.

    environment variables:
        {SERVICE}_LOG_LEVEL: service-specific log level (e.g., MOTOR_LOG_LEVEL)
        LOG_LEVEL: fallback log level for all services
        LOG_FORMAT: "json" for structured logging, "text" for development
    """
    if service in _configured_services:
        return

    log_level = getattr(logging, level, None) if level else _get_log_level(service)
    fmt = log_format or _get_log_format()

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    if fmt == "json":
        handler.setFormatter(JSONFormatter(service))
    else:
        handler.setFormatter(TextFormatter(service))

    root_logger.addHandler(handler)

    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("grpc").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _configured_services.add(service)


def get_logger(name: str) -> logging.Logger:
    """get a logger instance.

    this is a convenience wrapper around logging.getLogger that ensures
    consistent logger naming across the codebase.
    """
    return logging.getLogger(name)
