import json
import logging
import logging.handlers
import re

import httpx
import pytest

from app import logging_config
from app.config import settings
from app.constants import (
    LOG_FILE_NAME,
    LOG_FRAMEWORK_LOGGER_NAMES,
    LOG_QUIET_LOGGER_NAMES,
)
from app.logging_config import (
    HttpLogShipHandler,
    JsonLogFormatter,
    _text_formatter,
    configure_logging,
    shutdown_log_shipping,
)

TS_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


@pytest.fixture(autouse=True)
def _restore_logging():
    root = logging.getLogger()
    original_root_handlers = root.handlers[:]
    original_root_level = root.level
    framework_state = {
        name: (
            logging.getLogger(name).handlers[:],
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in LOG_FRAMEWORK_LOGGER_NAMES
    }
    quiet_state = {
        name: logging.getLogger(name).level for name in LOG_QUIET_LOGGER_NAMES
    }

    yield

    shutdown_log_shipping()
    root.handlers[:] = original_root_handlers
    root.setLevel(original_root_level)
    for name, (handlers, level, propagate) in framework_state.items():
        logger = logging.getLogger(name)
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate
    for name, level in quiet_state.items():
        logging.getLogger(name).setLevel(level)


def _make_record(msg: str = "hello", exc_info=None) -> logging.LogRecord:
    return logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )


def test_text_formatter_includes_timestamp() -> None:
    formatted = _text_formatter().format(_make_record())
    assert TS_PREFIX_RE.match(formatted)
    assert "INFO" in formatted
    assert "hello" in formatted


def test_text_formatter_escapes_embedded_newlines() -> None:
    # An untrusted value (e.g. a raw email subject) containing CR/LF must not
    # be able to forge extra fake log lines in the dev console.
    formatted = _text_formatter().format(
        _make_record("line one\nWARNING app.evil: fake injected line\r\nline two")
    )
    assert "\n" not in formatted
    assert "\r" not in formatted
    assert "line one\\nWARNING app.evil: fake injected line\\r\\nline two" in formatted


def test_json_formatter_shape() -> None:
    formatted = JsonLogFormatter().format(_make_record())
    payload = json.loads(formatted)
    assert set(["ts", "level", "logger", "msg"]).issubset(payload.keys())
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["msg"] == "hello"
    assert "exc" not in payload


def test_json_formatter_merges_extra_fields() -> None:
    # Fields passed via logger.x(..., extra={...}) become top-level JSON keys so
    # log drains can filter on structured fields instead of regex-parsing msg.
    record = _make_record("job done")
    record.event = "job_run"
    record.job = "build_daily_feeds"
    record.status = "ok"
    record.duration_ms = 42

    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["event"] == "job_run"
    assert payload["job"] == "build_daily_feeds"
    assert payload["status"] == "ok"
    assert payload["duration_ms"] == 42
    assert payload["msg"] == "job done"


def test_json_formatter_extra_cannot_overwrite_reserved_keys() -> None:
    # A caller-supplied attribute must never clobber ts/level/logger/msg — the
    # standard-record scan skips reserved names and keys already in the payload.
    record = _make_record("real message")
    # "msg" is a standard LogRecord attr (reserved); a stray "logger" extra is not
    # a standard attr but is already a payload key, so both must be preserved.
    record.logger = "attacker.controlled"

    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["logger"] == "app.test"
    assert payload["msg"] == "real message"


def test_json_formatter_no_extras_shape_unchanged() -> None:
    # Regression guard: a record with no extras yields exactly the original keys.
    payload = json.loads(JsonLogFormatter().format(_make_record()))
    assert set(payload.keys()) == {"ts", "level", "logger", "msg"}


def test_json_formatter_drops_uvicorn_color_message() -> None:
    # uvicorn adds extra={"color_message": ...} on its startup/shutdown lines;
    # it's reserved so it never pollutes the curated shipped schema.
    record = _make_record("Uvicorn running")
    record.color_message = "Uvicorn running \x1b[36m..."

    payload = json.loads(JsonLogFormatter().format(record))
    assert "color_message" not in payload


def test_json_formatter_non_serializable_extra_does_not_crash() -> None:
    # default=str keeps an arbitrary extra value from raising in the formatter
    # (and, in prod, on the log-shipping thread).
    record = _make_record("with object")
    record.obj = object()

    payload = json.loads(JsonLogFormatter().format(record))
    assert isinstance(payload["obj"], str)


def test_json_formatter_includes_exc_info() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _make_record("failed", exc_info=sys.exc_info())

    payload = json.loads(JsonLogFormatter().format(record))
    assert "exc" in payload
    assert "ValueError" in payload["exc"]


def test_configure_logging_idempotent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path)

    configure_logging()
    first_count = len(logging.getLogger().handlers)

    configure_logging()
    second_count = len(logging.getLogger().handlers)

    assert first_count == second_count


def test_dev_adds_rotating_file_handler(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path)

    configure_logging()

    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert (tmp_path / LOG_FILE_NAME).exists()

    console_handlers = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(console_handlers) == 1
    assert not isinstance(console_handlers[0].formatter, JsonLogFormatter)


def test_prod_uses_json_console_no_file_handler(monkeypatch) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "LOG_SHIP_URL", "")

    configure_logging()

    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert file_handlers == []

    console_handlers = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.handlers.QueueHandler)
    ]
    assert len(console_handlers) == 1
    assert isinstance(console_handlers[0].formatter, JsonLogFormatter)

    queue_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.QueueHandler)
    ]
    assert queue_handlers == []


def test_prod_with_ship_url_starts_queue_listener(monkeypatch) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "LOG_SHIP_URL", "https://logs.example.com/ingest")
    monkeypatch.setattr(settings, "LOG_SHIP_TOKEN", "secret-token")

    configure_logging()

    root = logging.getLogger()
    queue_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.QueueHandler)
    ]
    assert len(queue_handlers) == 1
    assert logging_config._queue_listener is not None


def test_ship_mode_silences_httpx_httpcore(monkeypatch) -> None:
    # httpx/httpcore's own per-request INFO lines would otherwise get shipped,
    # and the ship POST is itself an httpx request — a self-amplifying loop.
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "LOG_SHIP_URL", "https://logs.example.com/ingest")
    monkeypatch.setattr(settings, "LOG_SHIP_TOKEN", "secret-token")

    configure_logging()

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING

    record = _make_record("HTTP Request: POST https://api.axiom.co/ingest")
    record.name = "httpx"
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
    assert record.levelno < logging.getLogger("httpx").level


def test_http_log_ship_handler_emit_posts_json_with_bearer(monkeypatch) -> None:
    monkeypatch.setattr(settings, "LOG_SHIP_URL", "https://logs.example.com/ingest")
    monkeypatch.setattr(settings, "LOG_SHIP_TOKEN", "secret-token")

    captured = {}

    def fake_post(self, url, content=None, headers=None, **kwargs):
        captured["url"] = url
        captured["content"] = content
        captured["headers"] = headers
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    handler = HttpLogShipHandler()
    handler.emit(_make_record("shipped"))

    assert captured["url"] == "https://logs.example.com/ingest"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    payload = json.loads(captured["content"])
    assert isinstance(payload, list)
    assert payload[0]["msg"] == "shipped"


def test_http_log_ship_handler_swallows_network_errors(monkeypatch) -> None:
    monkeypatch.setattr(settings, "LOG_SHIP_URL", "https://logs.example.com/ingest")
    monkeypatch.setattr(settings, "LOG_SHIP_TOKEN", "secret-token")

    def fake_post(self, url, content=None, headers=None, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    handler = HttpLogShipHandler()
    # Should not raise — handleError() swallows it.
    handler.emit(_make_record("shipped"))


def test_framework_loggers_propagate_after_configure(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path)

    configure_logging()

    for name in LOG_FRAMEWORK_LOGGER_NAMES:
        logger = logging.getLogger(name)
        assert logger.propagate is True
        assert logger.handlers == []


def test_sqlalchemy_engine_logs_at_info_in_dev(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path)

    configure_logging()

    assert logging.getLogger("sqlalchemy.engine").level == logging.INFO


def test_sqlalchemy_engine_logs_at_warning_in_prod(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path)

    configure_logging()

    assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING
