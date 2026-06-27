"""Link Home Assistant contexts to OpenTelemetry span contexts."""

# ruff: noqa: SLF001

from opentelemetry import context as otel_context, trace
from opentelemetry.trace import NonRecordingSpan, Span, SpanContext

from homeassistant.core import Context, HomeAssistant

from .const import CONTEXT_REGISTRY_KEY, OTEL_CONTEXT_CACHE_KEY
from .propagation import (
    otel_context_from_carrier,
    store_trace_carrier_on_context,
    trace_carrier_from_ha_context,
    trace_carrier_from_span,
)


def store_linked_span_context(
    ha_context: Context,
    registry: dict[str, SpanContext],
    span: Span,
) -> None:
    """Remember a span context for later Home Assistant context correlation."""
    span_context = span.get_span_context()
    if not span_context.is_valid:
        return

    cache = ha_context._cache
    cache[OTEL_CONTEXT_CACHE_KEY] = span_context
    store_trace_carrier_on_context(ha_context, trace_carrier_from_span(span))
    registry[ha_context.id] = span_context


def lookup_parent_span_context(
    hass: HomeAssistant,
    ha_context: Context | None,
) -> SpanContext | None:
    """Find the parent span context for a Home Assistant context."""
    if ha_context is None:
        return None

    registry: dict[str, SpanContext] | None = hass.data.get(CONTEXT_REGISTRY_KEY)
    if registry is not None:
        if ha_context.id in registry:
            return registry[ha_context.id]

        if ha_context.parent_id and ha_context.parent_id in registry:
            return registry[ha_context.parent_id]

    cache = ha_context._cache
    cached = cache.get(OTEL_CONTEXT_CACHE_KEY)
    if isinstance(cached, SpanContext) and cached.is_valid:
        return cached

    return None


def root_otel_context() -> otel_context.Context:
    """Return an empty OpenTelemetry context for root spans."""
    return otel_context.Context()


def resolve_parent_otel_context(
    hass: HomeAssistant,
    ha_context: Context | None,
) -> otel_context.Context | None:
    """Resolve the OpenTelemetry parent context for a new span."""
    parent_span_context = lookup_parent_span_context(hass, ha_context)
    if parent_span_context is not None:
        return otel_context_from_span_context(parent_span_context)

    current_span = trace.get_current_span()
    if current_span.is_recording():
        return otel_context.get_current()

    return None


def resolve_span_creation_context(
    hass: HomeAssistant,
    ha_context: Context | None,
) -> otel_context.Context:
    """Resolve the OpenTelemetry context to use when starting a span."""
    carrier = trace_carrier_from_ha_context(ha_context)
    if carrier:
        remote_context = otel_context_from_carrier(carrier)
        if remote_context is not None:
            return remote_context

    parent_otel_context = resolve_parent_otel_context(hass, ha_context)
    if parent_otel_context is not None:
        return parent_otel_context
    return root_otel_context()


def otel_context_from_span_context(span_context: SpanContext) -> otel_context.Context:
    """Build an OpenTelemetry context from a stored span context."""
    return trace.set_span_in_context(NonRecordingSpan(span_context))
