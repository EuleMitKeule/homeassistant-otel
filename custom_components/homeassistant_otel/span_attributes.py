"""Shared OpenTelemetry span attribute builders."""

from typing import Any

from homeassistant.components.script import EVENT_SCRIPT_STARTED
from homeassistant.const import (
    ATTR_DOMAIN,
    ATTR_ENTITY_ID,
    ATTR_NAME,
    ATTR_SERVICE,
    ATTR_SERVICE_DATA,
    EVENT_CALL_SERVICE,
    EVENT_STATE_CHANGED,
)
from homeassistant.core import Context, ServiceCall, State

from .const import (
    ATTR_CONTEXT_ID,
    ATTR_CONTEXT_PARENT_ID,
    ATTR_DEVICE_ID,
    ATTR_DEVICE_IEEE,
    ATTR_DEVICE_UNIQUE_ID,
    ATTR_ENTITY_ATTRIBUTES_CHANGED,
    ATTR_ENTITY_ATTRIBUTES_CHANGED_COUNT,
    ATTR_ENTITY_DOMAIN,
    ATTR_ENTITY_ID as ATTR_ENTITY_ID_SPAN,
    ATTR_ENTITY_STATE_NEW,
    ATTR_ENTITY_STATE_OLD,
    ATTR_EVENT_COMMAND,
    ATTR_EVENT_NAME,
    ATTR_EVENT_ORIGIN,
    ATTR_EVENT_SOURCE,
    ATTR_EVENT_TYPE,
    ATTR_HTTP_METHOD,
    ATTR_HTTP_ROUTE,
    ATTR_HTTP_TARGET,
    ATTR_MQTT_PAYLOAD_SIZE,
    ATTR_MQTT_QOS,
    ATTR_MQTT_RETAIN,
    ATTR_MQTT_TOPIC,
    ATTR_NODE_ID,
    ATTR_SERVICE_DOMAIN,
    ATTR_SERVICE_NAME,
    ATTR_SERVICE_TARGET_AREA,
    ATTR_SERVICE_TARGET_DEVICE,
    ATTR_SERVICE_TARGET_ENTITY,
    ATTR_WEBSOCKET_COMMAND,
    ATTR_WEBSOCKET_MESSAGE_ID,
    ATTR_WEBSOCKET_USER,
    ATTR_WEBSOCKET_USER_ID,
    ATTR_ZHA_CLUSTER_ID,
    ATTR_ZHA_CLUSTER_NAME,
    ATTR_ZHA_ENDPOINT_ID,
    MAX_ATTRIBUTE_VALUE_LENGTH,
    MAX_CHANGED_ATTRIBUTES,
)

EVENT_AUTOMATION_TRIGGERED = "automation_triggered"

type AttributeValue = str | int | bool
type SpanAttributes = dict[str, AttributeValue]

_TARGET_KEYS: tuple[tuple[str, str], ...] = (
    ("entity_id", ATTR_SERVICE_TARGET_ENTITY),
    ("device_id", ATTR_SERVICE_TARGET_DEVICE),
    ("area_id", ATTR_SERVICE_TARGET_AREA),
)

_GENERIC_EVENT_DATA_KEYS: tuple[tuple[str, str], ...] = (
    ("device_ieee", ATTR_DEVICE_IEEE),
    ("device_id", ATTR_DEVICE_ID),
    ("unique_id", ATTR_DEVICE_UNIQUE_ID),
    ("command", ATTR_EVENT_COMMAND),
    ("cluster_id", ATTR_ZHA_CLUSTER_ID),
    ("cluster_name", ATTR_ZHA_CLUSTER_NAME),
    ("endpoint_id", ATTR_ZHA_ENDPOINT_ID),
    ("node_id", ATTR_NODE_ID),
    ("name", ATTR_EVENT_NAME),
    ("source", ATTR_EVENT_SOURCE),
    ("manufacturer", "hass.device.manufacturer"),
    ("model", "hass.device.model"),
    ("command_type", ATTR_EVENT_COMMAND),
    ("args", "hass.event.args"),
)


def context_attributes(context: Context | None) -> SpanAttributes:
    """Return span attributes shared across a Home Assistant context."""
    if context is None:
        return {}

    attributes: SpanAttributes = {ATTR_CONTEXT_ID: context.id}
    if context.parent_id is not None:
        attributes[ATTR_CONTEXT_PARENT_ID] = context.parent_id
    if context.user_id is not None:
        attributes[ATTR_WEBSOCKET_USER_ID] = context.user_id
    return attributes


def event_attributes(
    event_type: str,
    origin: str,
    context: Context | None,
    event_data: Any | None,
) -> SpanAttributes:
    """Return span attributes for an event bus dispatch."""
    attributes = context_attributes(context)
    attributes[ATTR_EVENT_TYPE] = event_type
    attributes[ATTR_EVENT_ORIGIN] = origin

    if not isinstance(event_data, dict):
        return attributes

    if event_type == EVENT_CALL_SERVICE:
        attributes.update(_call_service_event_attributes(event_data))
    elif event_type == EVENT_STATE_CHANGED:
        attributes.update(_state_changed_event_attributes(event_data))
    elif event_type == EVENT_AUTOMATION_TRIGGERED:
        attributes.update(_automation_triggered_event_attributes(event_data))
    elif event_type == EVENT_SCRIPT_STARTED:
        attributes.update(_script_started_event_attributes(event_data))
    else:
        attributes.update(_generic_event_data_attributes(event_data))

    return attributes


def service_call_attributes(service_call: ServiceCall) -> SpanAttributes:
    """Return span attributes for a service execution."""
    attributes = context_attributes(service_call.context)
    attributes[ATTR_SERVICE_DOMAIN] = service_call.domain
    attributes[ATTR_SERVICE_NAME] = service_call.service

    entity_id = service_call.data.get("entity_id")
    _set_attribute(attributes, ATTR_ENTITY_ID_SPAN, entity_id)
    _set_entity_domain_attribute(attributes, entity_id)

    return attributes


def mqtt_message_attributes(
    *,
    topic: str,
    qos: int,
    retain: bool,
    payload_size: int,
) -> SpanAttributes:
    """Return span attributes for an MQTT message."""
    attributes: SpanAttributes = {
        ATTR_MQTT_TOPIC: _truncate_string(topic),
        ATTR_MQTT_QOS: qos,
        ATTR_MQTT_PAYLOAD_SIZE: payload_size,
    }
    if retain:
        attributes[ATTR_MQTT_RETAIN] = True
    return attributes


def rest_request_attributes(
    *,
    method: str,
    path: str,
    route_name: str | None,
    user_id: str | None,
    remote: str | None,
) -> SpanAttributes:
    """Return span attributes for a REST API request."""
    attributes: SpanAttributes = {
        ATTR_HTTP_METHOD: method.upper(),
        ATTR_HTTP_TARGET: _truncate_string(path),
    }
    if route_name:
        attributes[ATTR_HTTP_ROUTE] = route_name
    if user_id is not None:
        attributes[ATTR_WEBSOCKET_USER_ID] = user_id
    if remote:
        attributes["network.peer.address"] = remote
    return attributes


def websocket_attributes(
    *,
    command_type: str,
    message_id: int,
    user_name: str | None,
    user_id: str | None,
    remote: str | None,
    msg: dict[str, Any],
) -> SpanAttributes:
    """Return span attributes for a WebSocket API command."""
    attributes: SpanAttributes = {
        ATTR_WEBSOCKET_COMMAND: command_type,
        ATTR_WEBSOCKET_MESSAGE_ID: message_id,
    }

    if user_name:
        attributes[ATTR_WEBSOCKET_USER] = user_name
    if user_id is not None:
        attributes[ATTR_WEBSOCKET_USER_ID] = user_id
    if remote:
        attributes["network.peer.address"] = remote

    if command_type == "call_service":
        attributes.update(_websocket_call_service_attributes(msg))
    elif command_type in {"fire_event", "subscribe_events"}:
        _set_attribute(attributes, ATTR_EVENT_TYPE, msg.get("event_type"))

    return attributes


def _call_service_event_attributes(event_data: dict[str, Any]) -> SpanAttributes:
    """Return call_service event attributes."""
    attributes: SpanAttributes = {}
    _set_attribute(attributes, ATTR_SERVICE_DOMAIN, event_data.get(ATTR_DOMAIN))
    _set_attribute(attributes, ATTR_SERVICE_NAME, event_data.get(ATTR_SERVICE))

    service_data = event_data.get(ATTR_SERVICE_DATA)
    if isinstance(service_data, dict):
        _set_attribute(attributes, ATTR_ENTITY_ID_SPAN, service_data.get("entity_id"))
        _set_entity_domain_attribute(attributes, service_data.get("entity_id"))

    return attributes


def _state_changed_event_attributes(event_data: dict[str, Any]) -> SpanAttributes:
    """Return state_changed event attributes."""
    attributes: SpanAttributes = {}
    entity_id = event_data.get("entity_id")
    _set_attribute(attributes, ATTR_ENTITY_ID_SPAN, entity_id)
    _set_entity_domain_attribute(attributes, entity_id)

    old_state = event_data.get("old_state")
    new_state = event_data.get("new_state")
    if isinstance(old_state, State):
        _set_attribute(attributes, ATTR_ENTITY_STATE_OLD, old_state.state)
    if isinstance(new_state, State):
        _set_attribute(attributes, ATTR_ENTITY_STATE_NEW, new_state.state)

    if isinstance(old_state, State) and isinstance(new_state, State):
        if old_state.state == new_state.state:
            changed_attributes = _changed_entity_attributes(old_state, new_state)
            if changed_attributes:
                _set_attribute(
                    attributes,
                    ATTR_ENTITY_ATTRIBUTES_CHANGED,
                    ",".join(changed_attributes[:MAX_CHANGED_ATTRIBUTES]),
                )
                if len(changed_attributes) > MAX_CHANGED_ATTRIBUTES:
                    attributes[ATTR_ENTITY_ATTRIBUTES_CHANGED_COUNT] = len(
                        changed_attributes
                    )

    return attributes


def _automation_triggered_event_attributes(
    event_data: dict[str, Any],
) -> SpanAttributes:
    """Return automation_triggered event attributes."""
    attributes: SpanAttributes = {}
    _set_attribute(attributes, ATTR_EVENT_NAME, event_data.get(ATTR_NAME))
    _set_attribute(attributes, ATTR_ENTITY_ID_SPAN, event_data.get(ATTR_ENTITY_ID))
    _set_attribute(attributes, ATTR_EVENT_SOURCE, event_data.get("source"))
    _set_entity_domain_attribute(attributes, event_data.get(ATTR_ENTITY_ID))
    return attributes


def _script_started_event_attributes(event_data: dict[str, Any]) -> SpanAttributes:
    """Return script_started event attributes."""
    attributes: SpanAttributes = {}
    _set_attribute(attributes, ATTR_EVENT_NAME, event_data.get(ATTR_NAME))
    _set_attribute(attributes, ATTR_ENTITY_ID_SPAN, event_data.get(ATTR_ENTITY_ID))
    _set_entity_domain_attribute(attributes, event_data.get(ATTR_ENTITY_ID))
    return attributes


def _generic_event_data_attributes(event_data: dict[str, Any]) -> SpanAttributes:
    """Return generic event attributes from common integration event keys."""
    attributes: SpanAttributes = {}
    for event_key, attribute_key in _GENERIC_EVENT_DATA_KEYS:
        if event_key not in event_data:
            continue
        value = event_data[event_key]
        if isinstance(value, int):
            attributes[attribute_key] = value
        elif isinstance(value, str):
            _set_attribute(attributes, attribute_key, value)
        elif isinstance(value, bool):
            attributes[attribute_key] = value

    entity_id = event_data.get(ATTR_ENTITY_ID)
    if ATTR_ENTITY_ID_SPAN not in attributes:
        _set_attribute(attributes, ATTR_ENTITY_ID_SPAN, entity_id)
    _set_entity_domain_attribute(attributes, entity_id)
    return attributes


def _changed_entity_attributes(old_state: State, new_state: State) -> list[str]:
    """Return entity attribute names that changed."""
    all_keys = set(old_state.attributes) | set(new_state.attributes)
    return sorted(
        key
        for key in all_keys
        if old_state.attributes.get(key) != new_state.attributes.get(key)
    )


def _websocket_call_service_attributes(msg: dict[str, Any]) -> SpanAttributes:
    """Return call_service WebSocket command attributes."""
    attributes: SpanAttributes = {}
    _set_attribute(attributes, ATTR_SERVICE_DOMAIN, msg.get("domain"))
    _set_attribute(attributes, ATTR_SERVICE_NAME, msg.get("service"))

    service_data = msg.get("service_data")
    if isinstance(service_data, dict):
        _set_attribute(attributes, ATTR_ENTITY_ID_SPAN, service_data.get("entity_id"))
        _set_entity_domain_attribute(attributes, service_data.get("entity_id"))

    target = msg.get("target")
    if isinstance(target, dict):
        attributes.update(_target_attributes(target))

    if msg.get("return_response"):
        attributes["hass.service.return_response"] = True

    return attributes


def _target_attributes(target: dict[str, Any]) -> SpanAttributes:
    """Return normalized service target attributes."""
    attributes: SpanAttributes = {}
    for key, attribute in _TARGET_KEYS:
        _set_attribute(attributes, attribute, _normalize_target_value(target.get(key)))
    return attributes


def _normalize_target_value(value: Any) -> str | None:
    """Convert a service target field to a bounded string."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        string_values = [item for item in value if isinstance(item, str)]
        if not string_values:
            return None
        return ",".join(string_values[:10])
    return None


def _set_entity_domain_attribute(
    attributes: SpanAttributes,
    entity_id: Any,
) -> None:
    """Add the entity domain derived from an entity id."""
    if isinstance(entity_id, str):
        domain, _separator, _name = entity_id.partition(".")
        if _separator:
            _set_attribute(attributes, ATTR_ENTITY_DOMAIN, domain)
        return

    if isinstance(entity_id, list):
        for item in entity_id:
            if isinstance(item, str):
                domain, _separator, _name = item.partition(".")
                if _separator:
                    _set_attribute(attributes, ATTR_ENTITY_DOMAIN, domain)
                return


def _truncate_string(value: str) -> str:
    """Truncate a string to the configured attribute length."""
    if len(value) <= MAX_ATTRIBUTE_VALUE_LENGTH:
        return value
    return f"{value[: MAX_ATTRIBUTE_VALUE_LENGTH - 3]}..."


def _set_attribute(
    attributes: SpanAttributes,
    key: str,
    value: Any,
) -> None:
    """Set a primitive span attribute with bounded string values."""
    if value is None or value == "":
        return

    if isinstance(value, bool):
        attributes[key] = value
        return

    if isinstance(value, int):
        attributes[key] = value
        return

    if not isinstance(value, str):
        return

    attributes[key] = _truncate_string(value)
