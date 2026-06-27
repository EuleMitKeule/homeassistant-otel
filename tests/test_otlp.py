"""Tests for OTLP helpers."""

from custom_components.homeassistant_otel.otlp import (
    _resolve_grpc_endpoint,
    redact_endpoint,
)


def test_resolve_grpc_endpoint_without_scheme() -> None:
    """Bare host:port endpoints stay insecure."""
    assert _resolve_grpc_endpoint("localhost:4317") == ("localhost:4317", True)


def test_resolve_grpc_endpoint_with_http_scheme() -> None:
    """HTTP scheme maps to insecure gRPC."""
    assert _resolve_grpc_endpoint("http://localhost:4317") == ("localhost:4317", True)


def test_redact_endpoint() -> None:
    """Credentials are not included in redacted endpoints."""
    assert (
        redact_endpoint("http://user:pass@tempo.example.com:4318/v1/traces")
        == "http://tempo.example.com:4318/v1/traces"
    )
