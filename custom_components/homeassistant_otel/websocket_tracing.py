"""Automatic tracing for Home Assistant WebSocket API commands."""

# ruff: noqa: SLF001

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from functools import wraps
import logging
from typing import Any, cast

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Tracer
import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import (
    ActiveConnection,
    WebSocketCommandHandler,
)
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.typing import VolSchemaType

from .const import TRACEPARENT_KEY, TRACESTATE_KEY
from .propagation import (
    span_creation_context_from_carrier,
    store_trace_carrier_on_context,
    trace_carrier_from_ws_message,
)
from .span_attributes import websocket_attributes

_LOGGER = logging.getLogger(__name__)
_PATCH_STATE_KEY = "homeassistant_otel_websocket_patch"
_WS_COMMAND_ATTR = "_ws_command"
_WS_SCHEMA_ATTR = "_ws_schema"
_TRACE_CONTEXT_WS_SCHEMA: VolSchemaType = {
    vol.Optional(TRACEPARENT_KEY): str,
    vol.Optional(TRACESTATE_KEY): str,
}
_WS_COMMANDS_ACCEPTING_TRACE_CONTEXT: tuple[str, ...] = ("call_service",)


@dataclass
class WebSocketTracingPatch:
    """Installed WebSocket tracing hooks."""

    original_handle_async_response: Callable[..., Any]
    original_register_command: Callable[..., Any]
    original_connection_context: Callable[..., Context]
    restore_handlers: Callable[[], None]
    restore_schemas: Callable[[], None] = field(default_factory=lambda: lambda: None)


def install_websocket_tracing(
    hass: HomeAssistant,
    tracer: Tracer,
) -> WebSocketTracingPatch:
    """Instrument WebSocket API command handlers with OpenTelemetry spans."""
    if hass.data.get(_PATCH_STATE_KEY):
        msg = "WebSocket tracing is already installed"
        raise RuntimeError(msg)

    decorators_module = websocket_api.decorators
    original_handle_async_response = decorators_module._handle_async_response
    original_register_command = websocket_api.async_register_command
    original_connection_context = ActiveConnection.context
    restore_handlers = _wrap_existing_handlers(hass, tracer)
    restore_schemas = _extend_trace_context_ws_schemas(hass)

    def traced_connection_context(
        self: ActiveConnection,
        msg: dict[str, Any],
    ) -> Context:
        ha_context = original_connection_context(self, msg)
        if carrier := trace_carrier_from_ws_message(msg):
            store_trace_carrier_on_context(ha_context, carrier)
        return ha_context

    ActiveConnection.context = traced_connection_context

    async def traced_handle_async_response(
        func: websocket_api.const.AsyncWebSocketCommandHandler,
        hass: HomeAssistant,
        connection: ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        command_type = str(msg.get("type", "unknown"))

        async def wrapped_func(
            wrapped_hass: HomeAssistant,
            wrapped_connection: ActiveConnection,
            wrapped_msg: dict[str, Any],
        ) -> None:
            with _websocket_span(tracer, wrapped_connection, wrapped_msg, command_type):
                await func(wrapped_hass, wrapped_connection, wrapped_msg)

        await original_handle_async_response(
            wrapped_func,
            hass,
            connection,
            msg,
        )

    @callback
    def traced_register_command(
        hass: HomeAssistant,
        command_or_handler: str | WebSocketCommandHandler,
        handler: WebSocketCommandHandler | None = None,
        schema: VolSchemaType | None = None,
    ) -> None:
        if handler is None:
            message_handler = cast(WebSocketCommandHandler, command_or_handler)
            wrapped_handler = _wrap_handler(tracer, message_handler)
            original_register_command(hass, wrapped_handler)
            return

        resolved_schema = schema
        if (
            isinstance(command_or_handler, str)
            and command_or_handler in _WS_COMMANDS_ACCEPTING_TRACE_CONTEXT
            and schema is not None
        ):
            resolved_schema = schema.extend(_TRACE_CONTEXT_WS_SCHEMA)

        wrapped_handler = _wrap_handler(tracer, handler)
        original_register_command(
            hass, command_or_handler, wrapped_handler, resolved_schema
        )

    decorators_module._handle_async_response = traced_handle_async_response
    websocket_api.async_register_command = traced_register_command

    patch = WebSocketTracingPatch(
        original_handle_async_response=original_handle_async_response,
        original_register_command=original_register_command,
        original_connection_context=original_connection_context,
        restore_handlers=restore_handlers,
        restore_schemas=restore_schemas,
    )
    hass.data[_PATCH_STATE_KEY] = patch
    _LOGGER.debug("Installed WebSocket API tracing hooks")
    return patch


def uninstall_websocket_tracing(hass: HomeAssistant) -> None:
    """Remove WebSocket API tracing hooks."""
    patch = hass.data.pop(_PATCH_STATE_KEY, None)
    if patch is None:
        return

    websocket_api.decorators._handle_async_response = (
        patch.original_handle_async_response
    )
    websocket_api.async_register_command = patch.original_register_command
    ActiveConnection.context = patch.original_connection_context
    patch.restore_schemas()
    patch.restore_handlers()
    _LOGGER.debug("Removed WebSocket API tracing hooks")


def _extend_trace_context_ws_schemas(hass: HomeAssistant) -> Callable[[], None]:
    """Allow optional W3C trace fields on selected WebSocket command schemas."""
    handlers = hass.data.get(websocket_api.DOMAIN)
    if not handlers:
        return lambda: None

    original_schemas: dict[str, VolSchemaType | bool] = {}
    for command in _WS_COMMANDS_ACCEPTING_TRACE_CONTEXT:
        if command not in handlers:
            continue
        handler, schema = handlers[command]
        if schema is False:
            continue
        original_schemas[command] = schema
        handlers[command] = (handler, schema.extend(_TRACE_CONTEXT_WS_SCHEMA))

    def restore_schemas() -> None:
        current_handlers = hass.data.get(websocket_api.DOMAIN)
        if current_handlers is None:
            return
        for command, schema in original_schemas.items():
            handler, _ = current_handlers[command]
            current_handlers[command] = (handler, schema)

    return restore_schemas


def _wrap_existing_handlers(
    hass: HomeAssistant,
    tracer: Tracer,
) -> Callable[[], None]:
    """Wrap handlers that were registered before tracing was enabled."""
    handlers = hass.data.get(websocket_api.DOMAIN)
    if not handlers:
        return lambda: None

    original_handlers = dict(handlers)
    for command, (handler, schema) in original_handlers.items():
        handlers[command] = (_wrap_handler(tracer, handler, command), schema)

    def restore_handlers() -> None:
        current_handlers = hass.data.get(websocket_api.DOMAIN)
        if current_handlers is None:
            return
        current_handlers.update(original_handlers)

    return restore_handlers


def _wrap_handler(
    tracer: Tracer,
    handler: WebSocketCommandHandler,
    command_type: str | None = None,
) -> WebSocketCommandHandler:
    """Wrap a WebSocket handler if it executes synchronously on the event loop."""
    if _is_async_websocket_handler(handler):
        return handler

    resolved_command = command_type or (
        handler._ws_command  # type: ignore[attr-defined]
        if hasattr(handler, _WS_COMMAND_ATTR)
        else handler.__name__
    )

    @callback
    @wraps(handler)
    def traced_handler(
        hass: HomeAssistant,
        connection: ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        with _websocket_span(tracer, connection, msg, str(resolved_command)):
            handler(hass, connection, msg)

    if command_type is None and hasattr(handler, _WS_COMMAND_ATTR):
        traced_handler._ws_command = handler._ws_command  # type: ignore[attr-defined]
    if command_type is None and hasattr(handler, _WS_SCHEMA_ATTR):
        traced_handler._ws_schema = handler._ws_schema  # type: ignore[attr-defined]

    return traced_handler


def _is_async_websocket_handler(handler: WebSocketCommandHandler) -> bool:
    """Return True when the handler schedules work via async_response."""
    return handler.__code__.co_name == "schedule_handler"


def _websocket_span(
    tracer: Tracer,
    connection: ActiveConnection,
    msg: dict[str, Any],
    command_type: str,
) -> AbstractContextManager[trace.Span]:
    """Create a span for a WebSocket API command."""
    span_name = f"websocket_api/{command_type}"
    user = connection.user
    attributes = websocket_attributes(
        command_type=command_type,
        message_id=int(msg["id"]),
        user_name=user.name if user is not None else None,
        user_id=user.id if user is not None else None,
        remote=connection.remote,
        msg=msg,
    )

    return tracer.start_as_current_span(
        span_name,
        context=span_creation_context_from_carrier(trace_carrier_from_ws_message(msg)),
        kind=SpanKind.SERVER,
        attributes=attributes,
    )
