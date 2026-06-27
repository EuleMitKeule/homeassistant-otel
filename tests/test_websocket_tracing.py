"""Tests for WebSocket API tracing."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
from homeassistant.components import websocket_api
from homeassistant.components.websocket_api.decorators import (
    async_response,
    websocket_command,
)
from homeassistant.core import HomeAssistant, callback
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from custom_components.homeassistant_otel.const import (
    ATTR_WEBSOCKET_COMMAND,
    ATTR_WEBSOCKET_MESSAGE_ID,
)
from custom_components.homeassistant_otel.websocket_tracing import (
    _is_async_websocket_handler,
    _wrap_handler,
    install_websocket_tracing,
    uninstall_websocket_tracing,
)


@pytest.fixture
def span_exporter() -> InMemorySpanExporter:
    """Provide an in-memory span exporter."""
    return InMemorySpanExporter()


@pytest.fixture
def tracer(span_exporter: InMemorySpanExporter):
    """Provide a tracer backed by the in-memory exporter."""
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    return provider.get_tracer("test")


def test_is_async_websocket_handler() -> None:
    """Detect handlers wrapped by async_response."""

    @async_response
    async def async_handler(_hass, _connection, _msg) -> None:
        return None

    @callback
    def sync_handler(_hass, _connection, _msg) -> None:
        return None

    assert _is_async_websocket_handler(async_handler) is True
    assert _is_async_websocket_handler(sync_handler) is False


def test_sync_handler_creates_span(
    hass: HomeAssistant,
    tracer,
    span_exporter: InMemorySpanExporter,
) -> None:
    """Wrap synchronous WebSocket handlers with spans."""
    connection = _make_connection()
    msg = {"id": 7, "type": "test/sync"}

    @callback
    def sync_handler(_hass, _connection, _msg) -> None:
        return None

    wrapped = _wrap_handler(tracer, sync_handler, "test/sync")
    wrapped(hass, connection, msg)

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "websocket_api/test/sync"
    assert spans[0].attributes[ATTR_WEBSOCKET_COMMAND] == "test/sync"
    assert spans[0].attributes[ATTR_WEBSOCKET_MESSAGE_ID] == 7


async def test_async_handler_creates_span(
    hass: HomeAssistant,
    tracer,
    span_exporter: InMemorySpanExporter,
) -> None:
    """Patch async WebSocket handlers with spans."""
    install_websocket_tracing(hass, tracer)
    connection = _make_connection()
    msg = {"id": 3, "type": "test/async"}

    @websocket_command({"type": "test/async"})
    @async_response
    async def async_handler(_hass, _connection, _msg) -> None:
        return None

    websocket_api.async_register_command(hass, async_handler)
    handler, _schema = hass.data[websocket_api.DOMAIN]["test/async"]
    handler(hass, connection, msg)
    await hass.async_block_till_done()

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "websocket_api/test/async"

    uninstall_websocket_tracing(hass)


def _make_connection() -> Any:
    """Create a minimal ActiveConnection stand-in."""
    user = Mock()
    user.name = "test-user"
    user.id = "user-id"

    connection = Mock()
    connection.user = user
    connection.remote = "127.0.0.1"
    connection.async_handle_exception = Mock()
    return connection
