"""The Home Assistant OpenTelemetry integration."""

from dataclasses import dataclass
from functools import partial
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import CONF_AUTH_HEADER, CONF_ENDPOINT, CONF_PROTOCOL
from .event_tracing import (
    EventTracingPatch,
    install_event_tracing,
    uninstall_event_tracing,
)
from .mqtt_tracing import MqttTracingPatch, install_mqtt_tracing, uninstall_mqtt_tracing
from .otlp import (
    OtelAuthenticationError,
    OtelConnectionError,
    validate_trace_exporter_connection,
)
from .rest_tracing import RestTracingPatch, install_rest_tracing, uninstall_rest_tracing
from .service_tracing import (
    ServiceTracingPatch,
    install_service_tracing,
    uninstall_service_tracing,
)
from .tracing import TraceRuntime, setup_trace_runtime
from .websocket_event_propagation import (
    WebSocketEventPropagationPatch,
    install_websocket_event_propagation,
    uninstall_websocket_event_propagation,
)
from .websocket_tracing import (
    WebSocketTracingPatch,
    install_websocket_tracing,
    uninstall_websocket_tracing,
)

_LOGGER = logging.getLogger(__name__)

type HomeAssistantOtelConfigEntry = ConfigEntry[HomeAssistantOtelRuntimeData]


@dataclass
class HomeAssistantOtelRuntimeData:
    """Runtime data for the Home Assistant OpenTelemetry integration."""

    trace_runtime: TraceRuntime
    websocket_patch: WebSocketTracingPatch
    event_patch: EventTracingPatch
    service_patch: ServiceTracingPatch
    mqtt_patch: MqttTracingPatch | None
    rest_patch: RestTracingPatch
    websocket_event_propagation_patch: WebSocketEventPropagationPatch


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeAssistantOtelConfigEntry,
) -> bool:
    """Set up Home Assistant OpenTelemetry from a config entry."""
    endpoint = entry.data[CONF_ENDPOINT]
    protocol = entry.data[CONF_PROTOCOL]
    auth_header = entry.data.get(CONF_AUTH_HEADER)

    try:
        await hass.async_add_executor_job(
            validate_trace_exporter_connection,
            endpoint,
            protocol,
            auth_header,
        )
    except OtelAuthenticationError as err:
        msg = "OTLP authentication failed"
        raise ConfigEntryAuthFailed(msg) from err
    except OtelConnectionError as err:
        _LOGGER.warning("Unable to connect to OTLP endpoint %s: %s", endpoint, err)
        msg = f"Unable to connect to OTLP endpoint {endpoint}"
        raise ConfigEntryNotReady(msg) from err

    try:
        trace_runtime = await hass.async_add_executor_job(
            partial(
                setup_trace_runtime,
                endpoint=endpoint,
                protocol=protocol,
                auth_header=auth_header,
            ),
        )
    except Exception as err:
        _LOGGER.exception(
            "Unable to initialize the OTLP trace exporter for %s", endpoint
        )
        msg = f"Unable to initialize the OTLP trace exporter for {endpoint}"
        raise ConfigEntryNotReady(msg) from err

    websocket_patch = install_websocket_tracing(hass, trace_runtime.websocket_tracer)
    event_patch = install_event_tracing(hass, trace_runtime.event_tracer)
    websocket_event_propagation_patch = install_websocket_event_propagation()
    service_patch = install_service_tracing(hass, trace_runtime.service_tracer)
    mqtt_patch = install_mqtt_tracing(hass, trace_runtime.mqtt_tracer)
    rest_patch = install_rest_tracing(hass, trace_runtime.rest_tracer)

    entry.runtime_data = HomeAssistantOtelRuntimeData(
        trace_runtime=trace_runtime,
        websocket_patch=websocket_patch,
        event_patch=event_patch,
        service_patch=service_patch,
        mqtt_patch=mqtt_patch,
        rest_patch=rest_patch,
        websocket_event_propagation_patch=websocket_event_propagation_patch,
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: HomeAssistantOtelConfigEntry,
) -> bool:
    """Unload a Home Assistant OpenTelemetry config entry."""
    uninstall_rest_tracing(hass)
    uninstall_mqtt_tracing(hass)
    uninstall_service_tracing(hass)
    uninstall_event_tracing(hass)
    uninstall_websocket_event_propagation()
    uninstall_websocket_tracing(hass)
    await hass.async_add_executor_job(entry.runtime_data.trace_runtime.shutdown)
    return True
