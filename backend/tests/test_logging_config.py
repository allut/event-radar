import json
import logging
import logging.handlers
import re

import httpx
import pytest

from app import logging_config
from app.config import settings
from app.constants import LOG_FILE_NAME, LOG_FRAMEWORK_LOGGER_NAMES
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

    yield

    shutdown_log_shipping()
    root.handlers[:] = original_root_handlers
    root.setLevel(original_root_level)
    for name, (handlers, level, propagate) in framework_state.items():
        logger = logging.getLogger(name)
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate


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
    assert payload["msg"] == "shipped"


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
