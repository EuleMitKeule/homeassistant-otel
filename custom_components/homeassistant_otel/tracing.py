"""OpenTelemetry tracer provider setup."""

from dataclasses import dataclass
import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

from .const import (
    TRACER_NAME_EVENT_BUS,
    TRACER_NAME_MQTT,
    TRACER_NAME_REST,
    TRACER_NAME_SERVICE,
    TRACER_NAME_WEBSOCKET,
)
from .otlp import create_trace_exporter

_LOGGER = logging.getLogger(__name__)


@dataclass
class TraceRuntime:
    """Runtime state for OpenTelemetry trace export."""

    provider: TracerProvider
    websocket_tracer: Tracer
    event_tracer: Tracer
    service_tracer: Tracer
    mqtt_tracer: Tracer
    rest_tracer: Tracer

    def shutdown(self) -> None:
        """Shut down the tracer provider and flush pending spans."""
        self.provider.shutdown()


def setup_trace_runtime(
    *,
    endpoint: str,
    protocol: str,
    auth_header: str | None,
    service_name: str = "home-assistant",
) -> TraceRuntime:
    """Configure the global tracer provider and OTLP exporter."""
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = create_trace_exporter(endpoint, protocol, auth_header)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    websocket_tracer = provider.get_tracer(TRACER_NAME_WEBSOCKET)
    event_tracer = provider.get_tracer(TRACER_NAME_EVENT_BUS)
    service_tracer = provider.get_tracer(TRACER_NAME_SERVICE)
    mqtt_tracer = provider.get_tracer(TRACER_NAME_MQTT)
    rest_tracer = provider.get_tracer(TRACER_NAME_REST)
    _LOGGER.debug(
        "Configured OpenTelemetry trace export to %s via %s",
        endpoint,
        protocol,
    )
    return TraceRuntime(
        provider=provider,
        websocket_tracer=websocket_tracer,
        event_tracer=event_tracer,
        service_tracer=service_tracer,
        mqtt_tracer=mqtt_tracer,
        rest_tracer=rest_tracer,
    )
