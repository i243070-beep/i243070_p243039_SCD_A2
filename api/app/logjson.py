"""JSON logs to stdout, with the request id on every line (section 4.8).

A pod's filesystem is ephemeral, so logs go to stdout and nowhere else.
Pass structured fields with `extra=`:

    log.info("answered", extra={"top_k": 5, "chunk_ids": ids})
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Attributes every LogRecord has; anything else came from `extra=`.
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel("WARNING")
