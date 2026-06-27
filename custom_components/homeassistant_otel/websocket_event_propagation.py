"""Inject W3C trace context into Home Assistant websocket event payloads."""

# ruff: noqa: SLF001

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
import logging
from typing import Any

from homeassistant.components.websocket_api import messages
from homeassistant.const import COMPRESSED_STATE_CONTEXT
from homeassistant.core import Event, EventStateChangedData

from .propagation import event_dict_with_trace_context, trace_carrier_from_ha_context

_LOGGER = logging.getLogger(__name__)


@dataclass
class WebSocketEventPropagationPatch:
    """Installed websocket event propagation hooks."""

    original_event_message: Callable[..., dict[str, Any]]
    original_partial_cached_event_message: Callable[[Event[Any]], bytes]
    original_state_diff_event: Callable[
        [Event[EventStateChangedData]],
        dict[str, Any],
    ]


_PATCH_HOLDER: list[WebSocketEventPropagationPatch | None] = [None]


def install_websocket_event_propagation() -> WebSocketEventPropagationPatch:
    """Patch websocket event serialization to include W3C trace context."""
    if _PATCH_HOLDER[0] is not None:
        msg = "WebSocket event propagation is already installed"
        raise RuntimeError(msg)

    original_event_message = messages.event_message
    original_partial_cached_event_message = messages._partial_cached_event_message
    original_state_diff_event = messages._state_diff_event

    def traced_event_message(iden: int, event: Any) -> dict[str, Any]:
        if isinstance(event, Event):
            event = event_dict_with_trace_context(event)
        return original_event_message(iden, event)

    @lru_cache(maxsize=128)
    def traced_partial_cached_event_message(event: Event[Any]) -> bytes:
        event_dict = event_dict_with_trace_context(event)
        return (
            messages._message_to_json_bytes_or_none({
                "type": "event",
                "event": event_dict,
            })
            or messages.INVALID_JSON_PARTIAL_MESSAGE
        )

    def traced_state_diff_event(
        event: Event[EventStateChangedData],
    ) -> dict[str, Any]:
        result = original_state_diff_event(event)
        new_state = event.data["new_state"]
        if new_state is None:
            return result

        trace_fields = trace_carrier_from_ha_context(new_state.context)
        if not trace_fields:
            return result

        change = result.get(messages.ENTITY_EVENT_CHANGE)
        if not isinstance(change, dict):
            return result

        for diff in change.values():
            if not isinstance(diff, dict):
                continue
            additions = diff.get(messages.STATE_DIFF_ADDITIONS)
            if not isinstance(additions, dict):
                continue
            context_value = additions.get(COMPRESSED_STATE_CONTEXT)
            if isinstance(context_value, dict):
                additions[COMPRESSED_STATE_CONTEXT] = {
                    **context_value,
                    **trace_fields,
                }
            elif isinstance(context_value, str):
                additions[COMPRESSED_STATE_CONTEXT] = {
                    "id": context_value,
                    **trace_fields,
                }

        return result

    messages.event_message = traced_event_message
    messages._partial_cached_event_message = traced_partial_cached_event_message
    messages._state_diff_event = traced_state_diff_event

    patch = WebSocketEventPropagationPatch(
        original_event_message=original_event_message,
        original_partial_cached_event_message=original_partial_cached_event_message,
        original_state_diff_event=original_state_diff_event,
    )
    _PATCH_HOLDER[0] = patch
    _LOGGER.debug("Installed websocket event trace propagation hooks")
    return patch


def uninstall_websocket_event_propagation(
    patch: WebSocketEventPropagationPatch,
) -> None:
    """Remove websocket event propagation hooks."""
    messages.event_message = patch.original_event_message
    messages._partial_cached_event_message = patch.original_partial_cached_event_message
    messages._state_diff_event = patch.original_state_diff_event
    _PATCH_HOLDER[0] = None
    _LOGGER.debug("Removed websocket event trace propagation hooks")
