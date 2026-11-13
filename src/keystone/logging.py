"""Structured JSON logging (KFB-STD-001 section 4)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

_EXTRA_KEYS = ("program", "run_id", "event", "record_no")


def mask_account(acct_no: str) -> str:
    """Mask an account number to its last 4 characters (``****1809``)."""
    return "****" + acct_no.strip()[-4:]


class JsonFormatter(logging.Formatter):
    """One JSON object per line: timestamp (UTC), level, program, run_id, event, record_no."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
        }
        for key in _EXTRA_KEYS:
            payload[key] = getattr(record, key, None)
        return json.dumps(payload)


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the keystone namespace that writes JSON to stderr."""
    root = logging.getLogger("keystone")
    if not any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    return logging.getLogger(name)
