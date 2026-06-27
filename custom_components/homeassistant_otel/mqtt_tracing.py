"""Automatic tracing for MQTT messages."""

from collections.abc import Callable
from dataclasses import dataclass
import importlib
import logging
from typing import Any

from opentelemetry.trace import Tracer

from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.setup import EventComponentLoaded

_LOGGER = logging.getLogger(__name__)
_PATCH_STATE_KEY = "homeassistant_otel_mqtt_patch"
_LISTENER_KEY = "homeassistant_otel_mqtt_listener"
_MQTT_DOMAIN = "mqtt"
_MQTT_APPLY_MODULE = "homeassistant_otel.mqtt_apply"


@dataclass
class MqttTracingPatch:
    """Installed MQTT tracing hooks."""

    original_on_message: Callable[..., Any]


def install_mqtt_tracing(
    hass: HomeAssistant, tracer: Tracer
) -> MqttTracingPatch | None:
    """Instrument MQTT message handling with OpenTelemetry spans."""
    if hass.data.get(_PATCH_STATE_KEY):
        msg = "MQTT tracing is already installed"
        raise RuntimeError(msg)

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
    if patch is None:
        return

    mqtt_apply = importlib.import_module(_MQTT_APPLY_MODULE)
    mqtt_apply.remove_mqtt_patch(patch)


def _remove_mqtt_listener(hass: HomeAssistant) -> None:
    if listener := hass.data.pop(_LISTENER_KEY, None):
        listener()


def _apply_mqtt_patch(hass: HomeAssistant, tracer: Tracer) -> MqttTracingPatch:
    mqtt_apply = importlib.import_module(_MQTT_APPLY_MODULE)
    patch: MqttTracingPatch = mqtt_apply.apply_mqtt_patch(tracer)
    hass.data[_PATCH_STATE_KEY] = patch
    return patch
