"""Automatic tracing for Home Assistant REST API requests."""

# ruff: noqa: SLF001

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import logging
from typing import Any

from aiohttp import web
from aiohttp.web import StreamResponse
from aiohttp.web_urldispatcher import AbstractRoute
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Tracer

from homeassistant.components.http.const import KEY_HASS_USER
from homeassistant.core import HomeAssistant
import homeassistant.helpers.http as http_module
from homeassistant.helpers.http import HomeAssistantView

from .const import CONTEXT_REGISTRY_KEY
from .context_linking import store_linked_span_context
from .propagation import (
    span_creation_context_from_carrier,
    store_trace_carrier_on_context,
    trace_carrier_from_request,
)
from .span_attributes import rest_request_attributes

_LOGGER = logging.getLogger(__name__)
_PATCH_STATE_KEY = "homeassistant_otel_rest_patch"
_API_PATH_PREFIX = "/api"
_TRACED_HANDLER_IDS: set[int] = set()


@dataclass
class RestTracingPatch:
    """Installed REST API tracing hooks."""

    original_request_handler_factory: Callable[
        ..., Callable[..., Awaitable[StreamResponse]]
    ]
    original_register_view: Callable[..., None]
    original_view_context: Callable[..., Any]
    wrapped_route_handlers: list[
        tuple[AbstractRoute, Callable[..., Awaitable[StreamResponse]]]
    ] = field(default_factory=list)


def install_rest_tracing(hass: HomeAssistant, tracer: Tracer) -> RestTracingPatch:
    """Instrument REST API request handlers with OpenTelemetry spans."""
    if hass.data.get(_PATCH_STATE_KEY):
        msg = "REST API tracing is already installed"
        raise RuntimeError(msg)

    if not hasattr(hass, "http"):
        msg = "Home Assistant HTTP server is not available"
        raise RuntimeError(msg)

    original_request_handler_factory = http_module.request_handler_factory
    original_register_view = hass.http.register_view
    original_view_context = HomeAssistantView.context
    wrapped_route_handlers: list[
        tuple[AbstractRoute, Callable[..., Awaitable[StreamResponse]]]
    ] = []

    def traced_request_handler_factory(
        factory_hass: HomeAssistant,
        view: HomeAssistantView,
        handler: Callable[..., Any],
    ) -> Callable[[web.Request], Awaitable[StreamResponse]]:
        wrapped_handler = original_request_handler_factory(factory_hass, view, handler)
        return _wrap_request_handler(
            tracer,
            wrapped_handler,
            route_name=view.name if hasattr(view, "name") else None,
        )

    def traced_register_view(
        view: HomeAssistantView | type[HomeAssistantView],
    ) -> None:
        original_register_view(view)

    def traced_view_context(request: web.Request) -> Any:
        ha_context = original_view_context(request)
        store_trace_carrier_on_context(
            ha_context, trace_carrier_from_request(request)
        )
        current_span = trace.get_current_span()
        registry = hass.data.get(CONTEXT_REGISTRY_KEY)
        if (
            registry is not None
            and current_span.get_span_context().is_valid
            and current_span.is_recording()
        ):
            store_linked_span_context(ha_context, registry, current_span)
        return ha_context

    http_module.request_handler_factory = traced_request_handler_factory  # type: ignore[assignment]
    hass.http.register_view = traced_register_view  # type: ignore[method-assign]
    HomeAssistantView.context = staticmethod(traced_view_context)  # type: ignore[method-assign]

    for route in hass.http.app.router.routes():
        if not _is_api_route(route):
            continue
        original_handler = route.handler
        if id(original_handler) in _TRACED_HANDLER_IDS:
            continue
        route._handler = _wrap_request_handler(
            tracer,
            original_handler,
            route_name=route.name,
        )
        wrapped_route_handlers.append((route, original_handler))

    patch = RestTracingPatch(
        original_request_handler_factory=original_request_handler_factory,
        original_register_view=original_register_view,
        original_view_context=original_view_context,
        wrapped_route_handlers=wrapped_route_handlers,
    )
    hass.data[_PATCH_STATE_KEY] = patch
    _LOGGER.debug(
        "Installed REST API tracing on %s routes", len(wrapped_route_handlers)
    )
    return patch


def uninstall_rest_tracing(hass: HomeAssistant) -> None:
    """Remove REST API tracing hooks."""
    patch: RestTracingPatch | None = hass.data.pop(_PATCH_STATE_KEY, None)
    if patch is None:
        return

    for route, original_handler in patch.wrapped_route_handlers:
        route._handler = original_handler
        _TRACED_HANDLER_IDS.discard(id(original_handler))

    http_module.request_handler_factory = patch.original_request_handler_factory
    if hasattr(hass, "http"):
        hass.http.register_view = patch.original_register_view  # type: ignore[method-assign]
    HomeAssistantView.context = patch.original_view_context  # type: ignore[method-assign]
    _LOGGER.debug("Removed REST API tracing hooks")


def _wrap_request_handler(
    tracer: Tracer,
    handler: Callable[[web.Request], Awaitable[StreamResponse]],
    *,
    route_name: str | None,
) -> Callable[[web.Request], Awaitable[StreamResponse]]:
    """Wrap a request handler with an OpenTelemetry span."""
    if id(handler) in _TRACED_HANDLER_IDS:
        return handler

    async def traced_handle(request: web.Request) -> StreamResponse:
        hass_user = request.get(KEY_HASS_USER)
        user_id = hass_user.id if hass_user is not None else None
        attributes = rest_request_attributes(
            method=request.method,
            path=request.path,
            route_name=route_name,
            user_id=user_id,
            remote=request.remote,
        )
        with tracer.start_as_current_span(
            _span_name_from_request(request),
            context=span_creation_context_from_carrier(
                trace_carrier_from_request(request)
            ),
            kind=SpanKind.SERVER,
            attributes=attributes,
        ):
            return await handler(request)

    _TRACED_HANDLER_IDS.add(id(traced_handle))
    return traced_handle


def _span_name_from_request(request: web.Request) -> str:
    """Return a span name from the actual request path."""
    suffix = request.path.removeprefix(_API_PATH_PREFIX) or "/"
    return f"rest_api{suffix}"


def _is_api_route(route: AbstractRoute) -> bool:
    """Return True if the route serves the REST API."""
    resource = route.resource
    if resource is None:
        return False
    return bool(resource.canonical.startswith(_API_PATH_PREFIX))
