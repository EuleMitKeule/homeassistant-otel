"""Correlate inbound MQTT messages with recent mqtt.publish executions."""

from __future__ import annotations

import threading
import time
from typing import Any

from .const import TRACEPARENT_KEY, TRACESTATE_KEY

_DEFAULT_TTL_SECONDS = 30.0
_lock = threading.Lock()
_pending: dict[tuple[str, str], tuple[dict[str, str], float]] = {}


def _normalize_payload(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    return str(payload)


def _related_topics(topic: str) -> tuple[str, ...]:
    """Return topic aliases used by Home Assistant MQTT discovery entities."""
    if topic.endswith("/state"):
        base = topic[: -len("/state")]
        return (topic, f"{base}/set", f"{base}/config")
    if topic.endswith("/set"):
        base = topic[: -len("/set")]
        return (topic, f"{base}/state", f"{base}/config")
    if topic.endswith("/config"):
        base = topic[: -len("/config")]
        return (topic, f"{base}/state", f"{base}/set")
    return (topic,)


def _purge_expired(now: float) -> None:
    expired = [key for key, (_carrier, expires_at) in _pending.items() if expires_at <= now]
    for key in expired:
        _pending.pop(key, None)


def register_mqtt_publish_carrier(
    topic: str,
    payload: Any,
    carrier: dict[str, str],
    *,
    ttl_seconds: float = _DEFAULT_TTL_SECONDS,
) -> None:
    """Remember W3C trace fields for a pending outbound MQTT publish."""
    if TRACEPARENT_KEY not in carrier:
        return

    normalized_payload = _normalize_payload(payload)
    expires_at = time.monotonic() + ttl_seconds
    with _lock:
        _purge_expired(expires_at)
        for related_topic in _related_topics(topic):
            _pending[(related_topic, normalized_payload)] = (dict(carrier), expires_at)
            _pending[(related_topic, "")] = (dict(carrier), expires_at)


def lookup_mqtt_publish_carrier(topic: str, payload: Any) -> dict[str, str]:
    """Return stored trace fields for a recently published MQTT message."""
    normalized_payload = _normalize_payload(payload)
    now = time.monotonic()
    with _lock:
        _purge_expired(now)
        for candidate_topic in _related_topics(topic):
            for candidate_payload in (normalized_payload, ""):
                entry = _pending.pop((candidate_topic, candidate_payload), None)
                if entry is None:
                    continue
                carrier, expires_at = entry
                if expires_at > now and TRACEPARENT_KEY in carrier:
                    return dict(carrier)
    return {}


__all__ = ["lookup_mqtt_publish_carrier", "register_mqtt_publish_carrier"]
