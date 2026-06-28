"""Automatic tracing for MQTT messages."""

from collections.abc import Callable
from dataclasses import dataclass
import logging
from types import ModuleType
from typing import Any

from opentelemetry.trace import Tracer

from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.setup import EventComponentLoaded

_LOGGER = logging.getLogger(__name__)
_PATCH_STATE_KEY = "homeassistant_otel_mqtt_patch"
_LISTENER_KEY = "homeassistant_otel_mqtt_listener"
_MQTT_APPLY_MODULE_KEY = "homeassistant_otel_mqtt_apply_module"
_MQTT_DOMAIN = "mqtt"


@dataclass
class MqttTracingPatch:
    """Installed MQTT tracing hooks."""

    original_on_message: Callable[..., Any]
    original_async_publish: Callable[..., Any]


def install_mqtt_tracing(
    hass: HomeAssistant, tracer: Tracer, mqtt_apply: ModuleType
) -> MqttTracingPatch | None:
    """Instrument MQTT message handling with OpenTelemetry spans."""
    if hass.data.get(_PATCH_STATE_KEY):
        msg = "MQTT tracing is already installed"
        raise RuntimeError(msg)

    hass.data[_MQTT_APPLY_MODULE_KEY] = mqtt_apply

    if _MQTT_DOMAIN in hass.config.components:
        return _apply_mqtt_patch(hass, tracer)

    @callback
    def _on_component_loaded(event: Event[EventComponentLoaded]) -> None:
        if event.data["component"] != _MQTT_DOMAIN:
            return
        _remove_mqtt_listener(hass)
        _apply_mqtt_patch(hass, tracer)

    hass.data[_LISTENER_KEY] = hass.bus.async_listen(
        EVENT_COMPONENT_LOADED, _on_component_loaded
    )
    _LOGGER.debug("Deferred MQTT tracing until the mqtt component is loaded")
    return None


def uninstall_mqtt_tracing(hass: HomeAssistant) -> None:
    """Remove MQTT tracing hooks."""
    _remove_mqtt_listener(hass)
    patch: MqttTracingPatch | None = hass.data.pop(_PATCH_STATE_KEY, None)
    mqtt_apply: ModuleType | None = hass.data.pop(_MQTT_APPLY_MODULE_KEY, None)
    if patch is None or mqtt_apply is None:
        return

    mqtt_apply.remove_mqtt_patch(patch)


def _remove_mqtt_listener(hass: HomeAssistant) -> None:
    if listener := hass.data.pop(_LISTENER_KEY, None):
        listener()


def _apply_mqtt_patch(hass: HomeAssistant, tracer: Tracer) -> MqttTracingPatch:
    mqtt_apply: ModuleType = hass.data[_MQTT_APPLY_MODULE_KEY]
    patch: MqttTracingPatch = mqtt_apply.apply_mqtt_patch(tracer)
    hass.data[_PATCH_STATE_KEY] = patch
    return patch
