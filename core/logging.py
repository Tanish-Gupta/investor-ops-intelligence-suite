"""Logging (rule P6): JSON lines; PII is redacted in every record before it is emitted.

Ported from M3 `advisor_agent/logging.py`, using the Presidio-based `core.pii.redact`. Exception
text and stack traces are redacted too, and list/dict extras are scrubbed recursively.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import get_settings

_STD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}
_guard = threading.local()


def _redact(value: Any) -> Any:
    from core import pii

    if isinstance(value, str):
        return pii.redact(value)
    if isinstance(value, dict | list | tuple):
        return pii.scrub(value)
    return value


class PIIRedactionFilter(logging.Filter):
    """Redact the message, args, extras and exception text of every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(_guard, "active", False):  # records emitted while redacting (e.g. Presidio)
            return True
        _guard.active = True
        try:
            # Render the message first so args can never leak through %-formatting.
            record.msg = _redact(record.getMessage())
            record.args = None
            for key, value in list(vars(record).items()):
                if key not in _STD_ATTRS:
                    setattr(record, key, _redact(value))
            if record.exc_info:
                record.exc_text = _redact(logging.Formatter().formatException(record.exc_info))
                record.exc_info = None
        finally:
            _guard.active = False
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, get_settings().tz).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({k: v for k, v in vars(record).items() if k not in _STD_ATTRS})
        if record.exc_text:
            payload["exc"] = record.exc_text
        return json.dumps(payload, default=str, ensure_ascii=False)


_configured = False


def configure_logging(
    level: str | None = None, *, log_file: Path | None = None, force: bool = False
) -> None:
    """Install redacting JSON handlers on the root logger (stderr + optional file)."""
    global _configured
    if _configured and not force:
        return
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    for h in handlers:
        h.addFilter(PIIRedactionFilter())
        h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = handlers
    root.setLevel(level or get_settings().log_level)
    for noisy in ("presidio-analyzer", "presidio-anonymizer", "LiteLLM", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True
