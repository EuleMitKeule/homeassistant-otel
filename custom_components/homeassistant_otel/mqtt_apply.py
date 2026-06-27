"""Apply MQTT OpenTelemetry tracing patches."""

# ruff: noqa: SLF001

import logging

from opentelemetry.trace import SpanKind, Tracer
import paho.mqtt.client as paho_mqtt

from homeassistant.components import mqtt
from homeassistant.components.mqtt import MQTT
from homeassistant.core import callback

from .context_linking import root_otel_context
from .mqtt_tracing import MqttTracingPatch
from .span_attributes import mqtt_message_attributes

_LOGGER = logging.getLogger(__name__)


def apply_mqtt_patch(tracer: Tracer) -> MqttTracingPatch:
    """Patch MQTT message handling with OpenTelemetry spans."""
    original_on_message = mqtt.client.MQTT._async_mqtt_on_message

    @callback
    def traced_on_message(
        self: MQTT,
        _mqttc: paho_mqtt.Client,
        _userdata: None,
        msg: paho_mqtt.MQTTMessage,
    ) -> None:
        try:
            topic = msg.topic
        except UnicodeDecodeError:
            original_on_message(self, _mqttc, _userdata, msg)
            return

        payload_size = len(msg.payload) if msg.payload is not None else 0
        attributes = mqtt_message_attributes(
            topic=topic,
            qos=msg.qos,
            retain=msg.retain,
            payload_size=payload_size,
        )
        with tracer.start_as_current_span(
            "mqtt/message",
            context=root_otel_context(),
            kind=SpanKind.CONSUMER,
            attributes=attributes,
        ):
            original_on_message(self, _mqttc, _userdata, msg)

    mqtt.client.MQTT._async_mqtt_on_message = traced_on_message  # type: ignore[method-assign]

    patch = MqttTracingPatch(original_on_message=original_on_message)
    _LOGGER.debug("Installed MQTT tracing hooks")
    return patch


def remove_mqtt_patch(patch: MqttTracingPatch) -> None:
    """Restore the original MQTT message handler."""
    mqtt.client.MQTT._async_mqtt_on_message = patch.original_on_message  # type: ignore[method-assign]
    _LOGGER.debug("Removed MQTT tracing hooks")
