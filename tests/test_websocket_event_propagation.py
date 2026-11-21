"""Tests for websocket event trace-context injection."""

from __future__ import annotations

import json

from homeassistant.components.websocket_api import messages
from homeassistant.core import Context, Event

from custom_components.homeassistant_otel.propagation import (
    store_trace_carrier_on_context,
)
from custom_components.homeassistant_otel.websocket_event_propagation import (
    install_websocket_event_propagation,
    uninstall_websocket_event_propagation,
)

_TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def _event_with_traceparent() -> Event:
    context = Context(id="ctx-1")
    store_trace_carrier_on_context(context, {"traceparent": _TRACEPARENT})
    return Event("state_changed", {"entity_id": "light.test"}, context=context)


def test_cached_event_message_is_valid_json_with_traceparent() -> None:
    """Partial cache must omit the trailing brace so the subscription id fits."""
    event = _event_with_traceparent()
    patch = install_websocket_event_propagation()
    try:
        partial = messages._partial_cached_event_message(event)
        assert not partial.endswith(b"}")

        payload = json.loads(messages.cached_event_message(b"1", event))
        assert payload["id"] == 1
        assert payload["type"] == "event"
        assert payload["event"]["context"]["traceparent"] == _TRACEPARENT
    finally:
        uninstall_websocket_event_propagation(patch)
