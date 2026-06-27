"""OTLP trace exporter helpers shared across config flow and runtime setup."""

from http import HTTPStatus
import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from grpc import (
    Channel,
    RpcError,
    StatusCode,
    insecure_channel,
    secure_channel,
    ssl_channel_credentials,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter as OTLPSpanExporterGrpc,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as OTLPSpanExporterHttp,
)
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from opentelemetry.proto.collector.trace.v1.trace_service_pb2_grpc import (
    TraceServiceStub,
)
import requests

from .const import PROTOCOL_GRPC, VALIDATION_TIMEOUT_SECONDS

_LOGGER = logging.getLogger(__name__)
_OTLP_HTTP_HEADERS = {"content-type": "application/x-protobuf"}
_EMPTY_EXPORT_TRACE_REQUEST_BYTES = b""


class OtelConnectionError(Exception):
    """Raised when the OTLP endpoint cannot be reached or rejects the request."""


class OtelAuthenticationError(OtelConnectionError):
    """Raised when the OTLP endpoint rejects authentication."""


def create_trace_exporter(
    endpoint: str,
    protocol: str,
    auth_header: str | None,
    timeout_seconds: float | None = None,
) -> OTLPSpanExporterGrpc | OTLPSpanExporterHttp:
    """Create an OTLP trace exporter for the configured protocol."""
    timeout = timeout_seconds or VALIDATION_TIMEOUT_SECONDS

    if protocol == PROTOCOL_GRPC:
        grpc_endpoint, insecure = _resolve_grpc_endpoint(endpoint)
        headers = (("authorization", auth_header),) if auth_header else None
        return OTLPSpanExporterGrpc(
            endpoint=grpc_endpoint,
            headers=headers,
            insecure=insecure,
            timeout=timeout,
        )

    http_headers = {"authorization": auth_header} if auth_header else None
    return OTLPSpanExporterHttp(
        endpoint=endpoint,
        headers=http_headers,
        timeout=timeout,
    )


def validate_trace_exporter_connection(
    endpoint: str,
    protocol: str,
    auth_header: str | None,
    timeout_seconds: float = VALIDATION_TIMEOUT_SECONDS,
) -> None:
    """Validate that the configured OTLP endpoint accepts a trace export."""
    if protocol == PROTOCOL_GRPC:
        _validate_grpc_connection(endpoint, auth_header, timeout_seconds)
    else:
        _validate_http_connection(endpoint, auth_header, timeout_seconds)


def redact_endpoint(endpoint: str) -> str:
    """Return a sanitized endpoint safe to include in diagnostics."""
    parsed = urlsplit(endpoint)

    if not parsed.netloc:
        return endpoint

    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    sanitized_netloc = f"{host}{port}"

    return urlunsplit((
        parsed.scheme,
        sanitized_netloc,
        parsed.path,
        "",
        "",
    ))


def _resolve_grpc_endpoint(endpoint: str) -> tuple[str, bool]:
    """Normalize a gRPC endpoint for the Python OTLP exporter."""
    if "://" not in endpoint:
        return endpoint, True

    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = f"Invalid OTLP gRPC endpoint: {endpoint}"
        raise OtelConnectionError(msg)

    return parsed.netloc, parsed.scheme == "http"


def _create_grpc_channel(endpoint: str) -> Channel:
    """Create a gRPC channel for a validation request."""
    target, insecure = _resolve_grpc_endpoint(endpoint)
    if insecure:
        return insecure_channel(target)
    return secure_channel(target, ssl_channel_credentials())


def _validate_grpc_connection(
    endpoint: str,
    auth_header: str | None,
    timeout_seconds: float,
) -> None:
    """Validate a gRPC endpoint without relying on exporter internals."""
    channel = _create_grpc_channel(endpoint)
    metadata = (("authorization", auth_header),) if auth_header else None

    try:
        stub_factory: Any = TraceServiceStub
        stub = stub_factory(channel)
        stub.Export(
            request=trace_service_pb2.ExportTraceServiceRequest(),
            metadata=metadata,
            timeout=timeout_seconds,
        )
    except RpcError as err:
        if err.code() in (
            StatusCode.UNAUTHENTICATED,
            StatusCode.PERMISSION_DENIED,
        ):
            msg = "The OTLP endpoint rejected the authentication header"
            raise OtelAuthenticationError(msg) from err

        msg = f"Unable to export traces to the OTLP gRPC endpoint: {err.code()}"
        raise OtelConnectionError(msg) from err
    except Exception as err:
        msg = "Unable to reach the OTLP gRPC endpoint"
        raise OtelConnectionError(msg) from err
    finally:
        channel.close()


def _validate_http_connection(
    endpoint: str,
    auth_header: str | None,
    timeout_seconds: float,
) -> None:
    """Validate an HTTP endpoint without relying on exporter internals."""
    headers = dict(_OTLP_HTTP_HEADERS)
    if auth_header:
        headers["authorization"] = auth_header

    try:
        response = requests.post(
            endpoint,
            data=_EMPTY_EXPORT_TRACE_REQUEST_BYTES,
            headers=headers,
            timeout=timeout_seconds,
        )
    except requests.exceptions.RequestException as err:
        msg = "Unable to reach the OTLP HTTP endpoint"
        raise OtelConnectionError(msg) from err

    if response.ok:
        return

    if response.status_code in {
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
    }:
        msg = "The OTLP endpoint rejected the authentication header"
        raise OtelAuthenticationError(msg)

    msg = f"Unable to export traces to the OTLP HTTP endpoint: {response.status_code}"
    raise OtelConnectionError(msg)
