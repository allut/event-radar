import http
import json
import logging
import logging.handlers
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.constants.core import APP_ENV_DEVELOPMENT
from app.constants.http import (
    AUTHORIZATION_HEADER,
    BEARER_PREFIX,
    HEADER_CONTENT_TYPE,
    MIME_APPLICATION_JSON,
)
from app.constants.ops import (
    UVICORN_ACCESS_LOGGER,
    LOG_DATE_FORMAT,
    LOG_DIR_NAME,
    LOG_FILE_BACKUP_COUNT,
    LOG_FILE_MAX_BYTES,
    LOG_FILE_NAME,
    LOG_FORMAT_TEXT,
    LOG_FRAMEWORK_LOGGER_NAMES,
    LOG_QUIET_LOGGER_NAMES,
    LOG_RECORD_RESERVED_ATTRS,
    LOG_SHIP_BATCH_SIZE,
    LOG_SHIP_FLUSH_INTERVAL_SECONDS,
    LOG_SHIP_QUEUE_MAXSIZE,
    LOG_SHIP_SUPPRESS_ACCESS_PATHS,
    LOG_SHIP_TIMEOUT_SECONDS,
    SQLALCHEMY_ENGINE_LOGGER_NAME,
    UVICORN_ACCESS_PATH_ARG_INDEX,
    UVICORN_ACCESS_STATUS_ARG_INDEX,
)

_queue_listener: logging.handlers.QueueListener | None = None


class JsonLogFormatter(logging.Formatter):
    """Renders one JSON object per line: ts/level/logger/msg (+ exc when present).

    Any attribute a call site passes via ``extra={...}`` (e.g. event/job/status/
    duration_ms) is merged in as a top-level key, so log drains can filter on
    structured fields instead of regex-parsing ``msg``. Reserved keys are never
    overwritten; ``default=str`` keeps a non-JSON-serializable extra from crashing
    the formatter (and, in prod, the shipping thread).
    """

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
        for key, value in record.__dict__.items():
            if key not in LOG_RECORD_RESERVED_ATTRS and key not in payload:
                payload[key] = value
        return json.dumps(payload, default=str)


class HttpLogShipHandler(logging.Handler):
    """Batches formatted records and POSTs them to settings.LOG_SHIP_URL as one
    JSON array.

    emit() only buffers; a buffer reaching LOG_SHIP_BATCH_SIZE flushes at once,
    and a daemon timer thread flushes a partial buffer every
    LOG_SHIP_FLUSH_INTERVAL_SECONDS so a quiet app still ships promptly.
    close() flushes what is left. Network failures are swallowed via
    handleError() and the failed batch is dropped — log shipping must never
    crash the app. emit() runs on the QueueListener's background thread and the
    timer is its own thread, so nothing here blocks the event loop or request
    path; both paths take the handler lock only around the buffer swap, never
    around the POST.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonLogFormatter())
        self._client = httpx.Client(timeout=LOG_SHIP_TIMEOUT_SECONDS)
        self._buffer: list[str] = []
        self._last_record: logging.LogRecord | None = None
        self._stop = threading.Event()
        self._flusher = threading.Thread(
            target=self._flush_periodically, name="log-ship-flush", daemon=True
        )
        self._flusher.start()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            body = self.format(record)
        except Exception:
            self.handleError(record)
            return
        # handle() already holds self.lock (an RLock), so the append is
        # race-free against the timer thread, which takes it in flush().
        self._buffer.append(body)
        self._last_record = record
        if len(self._buffer) >= LOG_SHIP_BATCH_SIZE:
            self._send(*self._take_buffer())

    def flush(self) -> None:
        self.acquire()
        try:
            batch, record = self._take_buffer()
        finally:
            self.release()
        # POST outside the lock so a slow drain never stalls emit().
        self._send(batch, record)

    def _take_buffer(self) -> tuple[list[str], logging.LogRecord | None]:
        batch, self._buffer = self._buffer, []
        record, self._last_record = self._last_record, None
        return batch, record

    def _send(self, batch: list[str], record: logging.LogRecord | None) -> None:
        if not batch:
            return
        try:
            self._client.post(
                settings.LOG_SHIP_URL,
                # Axiom's ingest endpoint expects a JSON array of events, not a
                # bare object; also accepted by other JSON drains.
                content=f"[{','.join(batch)}]",
                headers={
                    HEADER_CONTENT_TYPE: MIME_APPLICATION_JSON,
                    AUTHORIZATION_HEADER: f"{BEARER_PREFIX}{settings.LOG_SHIP_TOKEN}",
                },
            )
        except Exception:
            if record is not None:
                self.handleError(record)

    def _flush_periodically(self) -> None:
        while not self._stop.wait(LOG_SHIP_FLUSH_INTERVAL_SECONDS):
            self.flush()

    def close(self) -> None:
        self._stop.set()
        self.flush()
        self._client.close()
        super().close()


class _AccessPathStripFilter(logging.Filter):
    """Strips the query string from every uvicorn.access record's path arg,
    in place, before ANY handler formats it.

    uvicorn.access records carry args = (client_addr, method, path,
    http_version, status); OAuth callback codes, unsubscribe tokens, and
    /explore search terms otherwise reach every sink verbatim — including
    Render's console log stream, a third-party retention surface, not just
    the Axiom drain (OWASP audit G-4; the original L-1 fix only stripped it
    for the shipping QueueHandler, since logging.Logger.callHandlers runs
    handlers in registration order and the console handler — registered
    first — had already formatted the record by the time a queue-handler-only
    filter ran). Attached to the uvicorn.access logger itself instead, so the
    mutation happens before any handler sees the record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if (
            record.name == UVICORN_ACCESS_LOGGER
            and isinstance(record.args, tuple)
            and len(record.args) > UVICORN_ACCESS_PATH_ARG_INDEX
        ):
            path = record.args[UVICORN_ACCESS_PATH_ARG_INDEX]
            if isinstance(path, str):
                stripped_path = path.split("?", 1)[0]
                if stripped_path != path:
                    record.args = (
                        record.args[:UVICORN_ACCESS_PATH_ARG_INDEX]
                        + (stripped_path,)
                        + record.args[UVICORN_ACCESS_PATH_ARG_INDEX + 1 :]
                    )
        return True


class _AccessPathSuppressFilter(logging.Filter):
    """Drops uvicorn.access records for high-frequency probe paths before
    they ship to Axiom.

    Matches the (already query-string-stripped, see _AccessPathStripFilter)
    path against LOG_SHIP_SUPPRESS_ACCESS_PATHS. Only a successful (< 400)
    response is suppressed — a failing health check is exactly the signal the
    Axiom monitor should see, so it still ships. Attached only to the
    shipping QueueHandler, so suppressed lines still reach the console
    handler (Render logs).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if (
            record.name == UVICORN_ACCESS_LOGGER
            and isinstance(record.args, tuple)
            and len(record.args) > UVICORN_ACCESS_STATUS_ARG_INDEX
        ):
            path = record.args[UVICORN_ACCESS_PATH_ARG_INDEX]
            status = record.args[UVICORN_ACCESS_STATUS_ARG_INDEX]
            if (
                path in LOG_SHIP_SUPPRESS_ACCESS_PATHS
                and isinstance(status, int)
                and status < http.HTTPStatus.BAD_REQUEST
            ):
                return False
        return True


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
        queue_handler = logging.handlers.QueueHandler(ship_queue)
        queue_handler.addFilter(_AccessPathSuppressFilter())
        root.addHandler(queue_handler)
        global _queue_listener
        _queue_listener = logging.handlers.QueueListener(
            ship_queue, HttpLogShipHandler()
        )
        _queue_listener.start()

    for name in LOG_FRAMEWORK_LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        if name == UVICORN_ACCESS_LOGGER:
            # Attached at the logger level (not a handler) so the mutation
            # runs before ANY handler formats the record — see
            # _AccessPathStripFilter's docstring (OWASP audit G-4).
            logger.filters.clear()
            logger.addFilter(_AccessPathStripFilter())
        if name == SQLALCHEMY_ENGINE_LOGGER_NAME:
            logger.setLevel(logging.INFO if is_dev else logging.WARNING)
        else:
            logger.setLevel(logging.NOTSET)

    for name in LOG_QUIET_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.WARNING)


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
