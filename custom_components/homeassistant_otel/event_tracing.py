"""Automatic tracing for Home Assistant event bus events."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
import logging
from types import TracebackType
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, SpanContext, SpanKind, Tracer

from homeassistant.components.websocket_api import ActiveConnection
from homeassistant.core import Context, EventBus, EventOrigin, HomeAssistant, callback
from homeassistant.util.event_type import EventType

from .const import CONTEXT_REGISTRY_KEY
from .context_linking import resolve_span_creation_context, store_linked_span_context
from .span_attributes import event_attributes

_LOGGER = logging.getLogger(__name__)
_PATCH_STATE_KEY = "homeassistant_otel_event_patch"


@dataclass
class EventTracingPatch:
    """Installed event bus tracing hooks."""

    original_async_fire_internal: Callable[..., Any]
    original_connection_context: Callable[..., Context]
    context_registry: dict[str, SpanContext]


def install_event_tracing(
    hass: HomeAssistant,
    tracer: Tracer,
) -> EventTracingPatch:
    """Instrument event bus dispatch with OpenTelemetry spans."""
    if hass.data.get(_PATCH_STATE_KEY):
        msg = "Event bus tracing is already installed"
        raise RuntimeError(msg)

    context_registry: dict[str, SpanContext] = {}
    hass.data[CONTEXT_REGISTRY_KEY] = context_registry

    original_async_fire_internal = EventBus.async_fire_internal
    original_connection_context = ActiveConnection.context

    @callback
    def traced_async_fire_internal(
        self: EventBus,
        event_type: EventType[Any] | str,
        event_data: Any | None = None,
        origin: EventOrigin = EventOrigin.local,
        context: Context | None = None,
        time_fired: float | None = None,
    ) -> None:
        with _event_span(
            hass,
            tracer,
            context_registry,
            event_type,
            event_data,
            origin,
            context,
        ):
            original_async_fire_internal(
                self,
                event_type,
                event_data,
                origin,
                context,
                time_fired,
            )

    def traced_connection_context(
        self: ActiveConnection,
        msg: dict[str, Any],
    ) -> Context:
        ha_context = original_connection_context(self, msg)
        current_span = trace.get_current_span()
        span_context = current_span.get_span_context()
        if span_context.is_valid and current_span.is_recording():
            store_linked_span_context(ha_context, context_registry, current_span)
        return ha_context

    EventBus.async_fire_internal = traced_async_fire_internal  # type: ignore[method-assign]
    ActiveConnection.context = traced_connection_context  # type: ignore[method-assign]

    patch = EventTracingPatch(
        original_async_fire_internal=original_async_fire_internal,
        original_connection_context=original_connection_context,
        context_registry=context_registry,
    )
    hass.data[_PATCH_STATE_KEY] = patch
    _LOGGER.debug("Installed event bus tracing hooks")
    return patch


def uninstall_event_tracing(hass: HomeAssistant) -> None:
    """Remove event bus tracing hooks."""
    patch: EventTracingPatch | None = hass.data.pop(_PATCH_STATE_KEY, None)
    if patch is None:
        return

    EventBus.async_fire_internal = patch.original_async_fire_internal  # type: ignore[method-assign]
    ActiveConnection.context = patch.original_connection_context  # type: ignore[method-assign]
    patch.context_registry.clear()
    hass.data.pop(CONTEXT_REGISTRY_KEY, None)
    _LOGGER.debug("Removed event bus tracing hooks")


def _event_span(
    hass: HomeAssistant,
    tracer: Tracer,
    context_registry: dict[str, SpanContext],
    event_type: EventType[Any] | str,
    event_data: Any | None,
    origin: EventOrigin,
    context: Context | None,
) -> AbstractContextManager[Span]:
    """Create a span for an event bus dispatch."""
    span_name = f"event/{event_type}"
    attributes = event_attributes(
        str(event_type),
        origin.value,
        context,
        event_data,
    )
    span_context = tracer.start_as_current_span(
        span_name,
        context=resolve_span_creation_context(hass, context),
        kind=SpanKind.INTERNAL,
        attributes=attributes,
    )

    return _register_context_on_span_enter(
        span_context,
        context,
        context_registry,
    )


def _register_context_on_span_enter(
    span_context: AbstractContextManager[Span],
    context: Context | None,
    context_registry: dict[str, SpanContext],
) -> AbstractContextManager[Span]:
    """Track the active event span on the Home Assistant context."""

    class _RegisteringSpanContext:
        """Context manager wrapper that registers span context on enter."""

        __slots__ = ("_context", "_context_registry", "_span_context")

        def __init__(
            self,
            span_context: AbstractContextManager[Span],
            context: Context | None,
            context_registry: dict[str, SpanContext],
        ) -> None:
            self._span_context = span_context
            self._context = context
            self._context_registry = context_registry

        def __enter__(self) -> Span:
            span = self._span_context.__enter__()
            if self._context is not None:
                store_linked_span_context(
                    self._context,
                    self._context_registry,
                    span,
                )
            return span

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
        ) -> None:
            self._span_context.__exit__(exc_type, exc_val, exc_tb)

    return _RegisteringSpanContext(span_context, context, context_registry)
