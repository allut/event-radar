import json
import logging
import logging.handlers
import queue
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.constants import (
    APP_ENV_DEVELOPMENT,
    LOG_DATE_FORMAT,
    LOG_DIR_NAME,
    LOG_FILE_BACKUP_COUNT,
    LOG_FILE_MAX_BYTES,
    LOG_FILE_NAME,
    LOG_FORMAT_TEXT,
    LOG_FRAMEWORK_LOGGER_NAMES,
    LOG_SHIP_QUEUE_MAXSIZE,
    LOG_SHIP_TIMEOUT_SECONDS,
)

_queue_listener: logging.handlers.QueueListener | None = None


class JsonLogFormatter(logging.Formatter):
    """Renders one JSON object per line: ts/level/logger/msg (+ exc when present)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


class HttpLogShipHandler(logging.Handler):
    """POSTs each formatted record to settings.LOG_SHIP_URL as JSON.

    Network failures are swallowed via handleError() — log shipping must never
    crash the app. Only ever runs on the QueueListener's background thread, so it
    never blocks the event loop or request path.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonLogFormatter())
        self._client = httpx.Client(timeout=LOG_SHIP_TIMEOUT_SECONDS)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            body = self.format(record)
            self._client.post(
                settings.LOG_SHIP_URL,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.LOG_SHIP_TOKEN}",
                },
            )
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        self._client.close()
        super().close()


class _DevTextFormatter(logging.Formatter):
    """Text formatter for local dev console output.

    Strips CR/LF from the fully-rendered line so an untrusted value
    interpolated into a log message (e.g. a raw email subject/header) can't
    forge extra fake log lines in the terminal. The prod JSON formatter
    already gets this for free (JSON-encoding escapes embedded newlines);
    most call sites already use %r for untrusted values too, but this closes
    the gap for any that don't.
    """

    def format(self, record: logging.LogRecord) -> str:
        return super().format(record).replace("\r", "\\r").replace("\n", "\\n")


def _text_formatter() -> logging.Formatter:
    formatter = _DevTextFormatter(LOG_FORMAT_TEXT, datefmt=LOG_DATE_FORMAT)
    formatter.converter = time.gmtime
    return formatter


def _build_console_handler(is_dev: bool) -> logging.Handler:
    handler = logging.StreamHandler()
    handler.setFormatter(_text_formatter() if is_dev else JsonLogFormatter())
    return handler


def _log_dir() -> Path:
    return Path(__file__).resolve().parent.parent / LOG_DIR_NAME


def _build_file_handler() -> logging.Handler:
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / LOG_FILE_NAME,
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(_text_formatter())
    return handler


def configure_logging() -> None:
    """Set up timestamped logging for app, uvicorn, and SQL echo loggers.

    Idempotent — safe to call repeatedly (e.g. under --reload or in tests): clears
    any previously configured root handlers and stops a prior shipping listener
    before reconfiguring.
    """
    is_dev = settings.APP_ENV == APP_ENV_DEVELOPMENT

    shutdown_log_shipping()
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    root.setLevel(settings.LOG_LEVEL)
    root.addHandler(_build_console_handler(is_dev))

    if is_dev:
        root.addHandler(_build_file_handler())

    if not is_dev and settings.LOG_SHIP_URL:
        ship_queue: queue.Queue = queue.Queue(LOG_SHIP_QUEUE_MAXSIZE)
        root.addHandler(logging.handlers.QueueHandler(ship_queue))
        global _queue_listener
        _queue_listener = logging.handlers.QueueListener(
            ship_queue, HttpLogShipHandler()
        )
        _queue_listener.start()

    for name in LOG_FRAMEWORK_LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        if name == "sqlalchemy.engine":
            logger.setLevel(logging.INFO if is_dev else logging.WARNING)
        else:
            logger.setLevel(logging.NOTSET)


def shutdown_log_shipping() -> None:
    """Stop the background log-shipping listener thread, if running.

    Log shipping must never crash the app — if the bounded queue is completely
    full at shutdown, enqueue_sentinel()'s put_nowait() raises queue.Full instead
    of blocking, which is swallowed here.
    """
    global _queue_listener
    if _queue_listener is not None:
        try:
            _queue_listener.stop()
        except queue.Full:
            pass
        for handler in _queue_listener.handlers:
            handler.close()
        _queue_listener = None
