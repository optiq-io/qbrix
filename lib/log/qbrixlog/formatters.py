from __future__ import annotations

import json
import logging
from datetime import datetime
from datetime import timezone
from typing import Any

from qbrixlog.context import get_request_id


class JSONFormatter(logging.Formatter):
    """json formatter for structured logging."""

    def __init__(self, service: str):
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = get_request_id()
        if request_id:
            log_data["request_id"] = request_id

        if hasattr(record, "experiment_id") and record.experiment_id:
            log_data["experiment_id"] = record.experiment_id

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "extra") and record.extra:
            log_data["extra"] = record.extra

        return json.dumps(log_data, default=str)


class TextFormatter(logging.Formatter):
    """text formatter for local development."""

    def __init__(self, service: str):
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        parts = [
            timestamp,
            f"[{record.levelname:<8}]",
            f"[{self._service}]",
            record.name,
            "-",
            record.getMessage(),
        ]

        request_id = get_request_id()
        if request_id:
            parts.insert(4, f"[{request_id[:8]}]")

        message = " ".join(parts)

        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)

        return message
