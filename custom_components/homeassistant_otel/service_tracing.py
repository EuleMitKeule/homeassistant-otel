"""Automatic tracing for Home Assistant service execution."""

# ruff: noqa: SLF001

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from opentelemetry.trace import SpanContext, SpanKind, Tracer

from homeassistant.core import (
    HomeAssistant,
    Service,
    ServiceCall,
    ServiceRegistry,
    ServiceResponse,
)

from .const import CONTEXT_REGISTRY_KEY
from .context_linking import resolve_span_creation_context, store_linked_span_context
from .span_attributes import service_call_attributes

_LOGGER = logging.getLogger(__name__)
_PATCH_STATE_KEY = "homeassistant_otel_service_patch"


@dataclass
class ServiceTracingPatch:
    """Installed service execution tracing hooks."""

    original_execute_service: Callable[..., Any]


def install_service_tracing(hass: HomeAssistant, tracer: Tracer) -> ServiceTracingPatch:
    """Instrument service execution with OpenTelemetry spans."""
    if hass.data.get(_PATCH_STATE_KEY):
        msg = "Service tracing is already installed"
        raise RuntimeError(msg)

    original_execute_service = ServiceRegistry._execute_service

    async def traced_execute_service(
        self: ServiceRegistry,
        handler: Service,
        service_call: ServiceCall,
    ) -> ServiceResponse:
        registry: dict[str, SpanContext] = hass.data.setdefault(
            CONTEXT_REGISTRY_KEY, {}
        )
        span_name = f"service/{service_call.domain}.{service_call.service}"
        attributes = service_call_attributes(service_call)
        span_context = tracer.start_as_current_span(
            span_name,
            context=resolve_span_creation_context(hass, service_call.context),
            kind=SpanKind.INTERNAL,
            attributes=attributes,
        )

        with span_context as span:
            store_linked_span_context(service_call.context, registry, span)
            return await original_execute_service(self, handler, service_call)

    ServiceRegistry._execute_service = traced_execute_service  # type: ignore[method-assign]

    patch = ServiceTracingPatch(original_execute_service=original_execute_service)
    hass.data[_PATCH_STATE_KEY] = patch
    _LOGGER.debug("Installed service execution tracing hooks")
    return patch


def uninstall_service_tracing(hass: HomeAssistant) -> None:
    """Remove service execution tracing hooks."""
    patch: ServiceTracingPatch | None = hass.data.pop(_PATCH_STATE_KEY, None)
    if patch is None:
        return

    ServiceRegistry._execute_service = patch.original_execute_service  # type: ignore[method-assign]
    _LOGGER.debug("Removed service execution tracing hooks")
