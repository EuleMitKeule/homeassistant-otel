"""Constants for the Home Assistant OpenTelemetry integration."""

from typing import Final

DOMAIN: Final = "homeassistant_otel"

CONF_ENDPOINT: Final = "endpoint"
CONF_PROTOCOL: Final = "protocol"
CONF_AUTH_HEADER: Final = "auth_header"

PROTOCOL_GRPC: Final = "grpc"
PROTOCOL_HTTP: Final = "http"

DEFAULT_ENDPOINT: Final = "http://localhost:4317"
DEFAULT_PROTOCOL: Final = PROTOCOL_GRPC
VALIDATION_TIMEOUT_SECONDS: Final = 5.0

ATTR_WEBSOCKET_COMMAND: Final = "hass.websocket.command"
ATTR_WEBSOCKET_MESSAGE_ID: Final = "hass.websocket.message_id"
ATTR_WEBSOCKET_USER: Final = "hass.websocket.user"
ATTR_WEBSOCKET_USER_ID: Final = "enduser.id"

ATTR_EVENT_TYPE: Final = "hass.event.type"
ATTR_EVENT_ORIGIN: Final = "hass.event.origin"
ATTR_CONTEXT_ID: Final = "hass.context.id"
ATTR_CONTEXT_PARENT_ID: Final = "hass.context.parent_id"

ATTR_SERVICE_DOMAIN: Final = "hass.service.domain"
ATTR_SERVICE_NAME: Final = "hass.service.name"
ATTR_SERVICE_TARGET_ENTITY: Final = "hass.service.target.entity_id"
ATTR_SERVICE_TARGET_DEVICE: Final = "hass.service.target.device_id"
ATTR_SERVICE_TARGET_AREA: Final = "hass.service.target.area_id"

ATTR_ENTITY_ID: Final = "hass.entity.id"
ATTR_ENTITY_DOMAIN: Final = "hass.entity.domain"
ATTR_ENTITY_STATE_OLD: Final = "hass.entity.state.old"
ATTR_ENTITY_STATE_NEW: Final = "hass.entity.state.new"
ATTR_ENTITY_ATTRIBUTES_CHANGED: Final = "hass.entity.attributes.changed"
ATTR_ENTITY_ATTRIBUTES_CHANGED_COUNT: Final = "hass.entity.attributes.changed_count"

ATTR_DEVICE_IEEE: Final = "hass.device.ieee"
ATTR_DEVICE_ID: Final = "hass.device.id"
ATTR_DEVICE_UNIQUE_ID: Final = "hass.device.unique_id"
ATTR_EVENT_COMMAND: Final = "hass.event.command"
ATTR_EVENT_SOURCE: Final = "hass.event.source"
ATTR_EVENT_NAME: Final = "hass.event.name"
ATTR_ZHA_CLUSTER_ID: Final = "hass.zha.cluster_id"
ATTR_ZHA_CLUSTER_NAME: Final = "hass.zha.cluster_name"
ATTR_ZHA_ENDPOINT_ID: Final = "hass.zha.endpoint_id"
ATTR_NODE_ID: Final = "hass.node.id"

ATTR_HTTP_METHOD: Final = "http.request.method"
ATTR_HTTP_ROUTE: Final = "http.route"
ATTR_HTTP_TARGET: Final = "url.path"

ATTR_MQTT_TOPIC: Final = "mqtt.topic"
ATTR_MQTT_QOS: Final = "mqtt.qos"
ATTR_MQTT_RETAIN: Final = "mqtt.retain"
ATTR_MQTT_PAYLOAD_SIZE: Final = "mqtt.payload.size_bytes"

MAX_CHANGED_ATTRIBUTES: Final = 20

MAX_ATTRIBUTE_VALUE_LENGTH: Final = 256

OTEL_CONTEXT_CACHE_KEY: Final = "homeassistant_otel_trace_context"
CONTEXT_REGISTRY_KEY: Final = "homeassistant_otel_context_registry"

TRACER_NAME_WEBSOCKET: Final = "homeassistant.websocket_api"
TRACER_NAME_EVENT_BUS: Final = "homeassistant.event_bus"
TRACER_NAME_SERVICE: Final = "homeassistant.service"
TRACER_NAME_MQTT: Final = "homeassistant.mqtt"
TRACER_NAME_REST: Final = "homeassistant.rest_api"
