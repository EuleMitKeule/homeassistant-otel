"""Tests for MQTT publish/message trace correlation."""

from __future__ import annotations

from custom_components.homeassistant_otel.mqtt_correlation import (
    lookup_mqtt_publish_carrier,
    register_mqtt_publish_carrier,
)


def test_lookup_links_state_publish_to_state_message() -> None:
    carrier = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
    register_mqtt_publish_carrier(
        "homeassistant/select/buro_light_automation_state/state",
        "Aktiv",
        carrier,
    )

    resolved = lookup_mqtt_publish_carrier(
        "homeassistant/select/buro_light_automation_state/state",
        b"Aktiv",
    )
    assert resolved == carrier


def test_lookup_links_state_publish_to_set_listener() -> None:
    carrier = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
    register_mqtt_publish_carrier(
        "homeassistant/select/foo/state",
        "on",
        carrier,
    )

    resolved = lookup_mqtt_publish_carrier("homeassistant/select/foo/set", "on")
    assert resolved == carrier
