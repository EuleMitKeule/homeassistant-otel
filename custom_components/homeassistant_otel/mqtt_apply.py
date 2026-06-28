"""Apply MQTT OpenTelemetry tracing patches."""

# ruff: noqa: SLF001

import logging

from opentelemetry.trace import SpanKind, Tracer
import paho.mqtt.client as paho_mqtt

from homeassistant.components import mqtt
from homeassistant.components.mqtt.client import MQTT, PublishPayloadType
from homeassistant.components.mqtt.const import DOMAIN, PROTOCOL_311
from homeassistant.const import CONF_PROTOCOL
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError

from .mqtt_correlation import lookup_mqtt_publish_carrier, register_mqtt_publish_carrier
from .mqtt_tracing import MqttTracingPatch
from .propagation import (
    inject_current_trace_into_mqtt_properties,
    span_creation_context_from_carrier,
    trace_carrier_from_mqtt_message,
    trace_carrier_from_span,
)
from .span_attributes import mqtt_message_attributes

_LOGGER = logging.getLogger(__name__)


def apply_mqtt_patch(tracer: Tracer) -> MqttTracingPatch:
    """Patch MQTT message handling with OpenTelemetry spans."""
    original_on_message = mqtt.client.MQTT._async_mqtt_on_message
    original_async_publish = MQTT.async_publish

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
        carrier = trace_carrier_from_mqtt_message(msg)
        if not carrier:
            carrier = lookup_mqtt_publish_carrier(topic, msg.payload)
        with tracer.start_as_current_span(
            "mqtt/message",
            context=span_creation_context_from_carrier(carrier),
            kind=SpanKind.CONSUMER,
            attributes=attributes,
        ):
            original_on_message(self, _mqttc, _userdata, msg)

    async def traced_async_publish(
        self: MQTT,
        topic: str,
        payload: PublishPayloadType,
        qos: int,
        retain: bool,
        *,
        message_expiry_interval: int | None = None,
    ) -> None:
        payload_size = 0 if payload is None else len(payload)
        attributes = mqtt_message_attributes(
            topic=topic,
            qos=qos,
            retain=retain,
            payload_size=payload_size,
        )
        with tracer.start_as_current_span(
            "mqtt/publish",
            kind=SpanKind.PRODUCER,
            attributes=attributes,
        ) as span:
            properties = paho_mqtt.Properties(paho_mqtt.PacketTypes.PUBLISH)  # type: ignore[no-untyped-call]
            if message_expiry_interval is not None:
                if not self.is_mqttv5:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="mqtt_message_expiry_interval_not_supported",
                        translation_placeholders={
                            "topic": topic,
                            "protocol": self.conf.get(CONF_PROTOCOL, PROTOCOL_311),
                        },
                    )
                properties.MessageExpiryInterval = message_expiry_interval
            if self.is_mqttv5:
                inject_current_trace_into_mqtt_properties(properties)
            register_mqtt_publish_carrier(
                topic,
                payload,
                trace_carrier_from_span(span),
            )
            msg_info = self._mqttc.publish(topic, payload, qos, retain, properties)
            _LOGGER.debug(
                "Transmitting%s message on %s: '%s', mid: %s, qos: %s,"
                " message_expiry_interval: %s",
                " retained" if retain else "",
                topic,
                payload,
                msg_info.mid,
                qos,
                message_expiry_interval,
            )
            await self._async_wait_for_mid_or_raise(msg_info.mid, msg_info.rc)

    mqtt.client.MQTT._async_mqtt_on_message = traced_on_message  # type: ignore[method-assign]
    MQTT.async_publish = traced_async_publish  # type: ignore[method-assign]

    patch = MqttTracingPatch(
        original_on_message=original_on_message,
        original_async_publish=original_async_publish,
    )
    _LOGGER.debug("Installed MQTT tracing hooks")
    return patch


def remove_mqtt_patch(patch: MqttTracingPatch) -> None:
    """Restore the original MQTT message handler."""
    mqtt.client.MQTT._async_mqtt_on_message = patch.original_on_message  # type: ignore[method-assign]
    MQTT.async_publish = patch.original_async_publish  # type: ignore[method-assign]
    _LOGGER.debug("Removed MQTT tracing hooks")
