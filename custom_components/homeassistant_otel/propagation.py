"""W3C Trace Context propagation for cross-process distributed tracing."""

# ruff: noqa: SLF001

from collections.abc import Mapping
from typing import Any

from aiohttp import web
from opentelemetry import context as otel_context, trace
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import Span

from homeassistant.core import Context, Event

from .const import (
    TRACEPARENT_CACHE_KEY,
    TRACEPARENT_KEY,
    TRACESTATE_CACHE_KEY,
    TRACESTATE_KEY,
)


def trace_carrier_from_span(span: Span) -> dict[str, str]:
    """Build a W3C trace carrier from an active span."""
    carrier: dict[str, str] = {}
    inject(carrier, context=trace.set_span_in_context(span))
    return carrier


def store_trace_carrier_on_context(
    ha_context: Context,
    carrier: Mapping[str, str],
) -> None:
    """Store W3C trace fields on a Home Assistant context for later propagation."""
    cache = ha_context._cache
    if traceparent := carrier.get(TRACEPARENT_KEY):
        cache[TRACEPARENT_CACHE_KEY] = traceparent
    if tracestate := carrier.get(TRACESTATE_KEY):
        cache[TRACESTATE_CACHE_KEY] = tracestate


def trace_carrier_from_ha_context(context: Context | None) -> dict[str, str]:
    """Return stored W3C trace fields from a Home Assistant context."""
    if context is None:
        return {}

    cache = context._cache
    carrier: dict[str, str] = {}
    if traceparent := cache.get(TRACEPARENT_CACHE_KEY):
        carrier[TRACEPARENT_KEY] = traceparent
    if tracestate := cache.get(TRACESTATE_CACHE_KEY):
        carrier[TRACESTATE_KEY] = tracestate
    return carrier


def trace_carrier_from_ws_message(msg: Mapping[str, Any]) -> dict[str, str]:
    """Extract W3C trace fields from a WebSocket API message."""
    carrier: dict[str, str] = {}
    if traceparent := msg.get(TRACEPARENT_KEY):
        if isinstance(traceparent, str):
            carrier[TRACEPARENT_KEY] = traceparent
    if tracestate := msg.get(TRACESTATE_KEY):
        if isinstance(tracestate, str):
            carrier[TRACESTATE_KEY] = tracestate
    return carrier


def trace_carrier_from_request(request: web.Request) -> dict[str, str]:
    """Extract W3C trace fields from an HTTP request."""
    carrier: dict[str, str] = {}
    if traceparent := request.headers.get(TRACEPARENT_KEY):
        carrier[TRACEPARENT_KEY] = traceparent
    if tracestate := request.headers.get(TRACESTATE_KEY):
        carrier[TRACESTATE_KEY] = tracestate
    return carrier


def otel_context_from_carrier(
    carrier: Mapping[str, str],
) -> otel_context.Context | None:
    """Extract an OpenTelemetry context from a W3C trace carrier."""
    if TRACEPARENT_KEY not in carrier:
        return None

    extracted = extract(carrier)
    span_context = trace.get_current_span(extracted).get_span_context()
    if span_context.is_valid:
        return extracted
    return None


def span_creation_context_from_carrier(
    carrier: Mapping[str, str],
) -> otel_context.Context:
    """Resolve span creation context from a remote carrier or start a new root."""
    remote_context = otel_context_from_carrier(carrier)
    if remote_context is not None:
        return remote_context
    return otel_context.Context()


def enrich_context_dict(
    context_dict: dict[str, Any], ha_context: Context
) -> dict[str, Any]:
    """Add W3C trace fields to a serialized Home Assistant context dict."""
    trace_fields = trace_carrier_from_ha_context(ha_context)
    if not trace_fields:
        return context_dict

    enriched = dict(context_dict)
    enriched.update(trace_fields)
    return enriched


def event_dict_with_trace_context(event: Event[Any]) -> dict[str, Any]:
    """Return a serializable event dict including W3C trace context."""
    event_dict = dict(event.as_dict())
    context_dict = event_dict["context"]
    if type(context_dict) is dict:
        event_dict["context"] = enrich_context_dict(context_dict, event.context)
    else:
        event_dict["context"] = enrich_context_dict(dict(context_dict), event.context)
    return event_dict


def inject_current_trace_into_mqtt_properties(properties: Any) -> None:
    """Inject the active W3C trace context into MQTT v5 User Properties."""
    current_span = trace.get_current_span()
    if not current_span.is_recording():
        return

    carrier = trace_carrier_from_span(current_span)
    if TRACEPARENT_KEY not in carrier:
        return

    user_properties = list(getattr(properties, "UserProperty", None) or [])
    existing_keys = {key for key, _value in user_properties}
    user_properties.extend(
        (key, carrier[key])
        for key in (TRACEPARENT_KEY, TRACESTATE_KEY)
        if key in carrier and key not in existing_keys
    )
    properties.UserProperty = user_properties


def trace_carrier_from_mqtt_message(msg: Any) -> dict[str, str]:
    """Extract W3C trace fields from an MQTT v5 message."""
    properties = getattr(msg, "properties", None)
    if properties is None:
        return {}

    user_properties = getattr(properties, "UserProperty", None)
    if not user_properties:
        user_properties = getattr(properties, "user_property", None)
    if not user_properties:
        return {}

    carrier: dict[str, str] = {}
    if isinstance(user_properties, dict):
        items = user_properties.items()
    else:
        items = user_properties

    for key, value in items:
        key_str = str(key)
        if key_str == TRACEPARENT_KEY and isinstance(value, str):
            carrier[TRACEPARENT_KEY] = value
        elif key_str == TRACESTATE_KEY and isinstance(value, str):
            carrier[TRACESTATE_KEY] = value
    return carrier
