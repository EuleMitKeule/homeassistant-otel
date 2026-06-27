"""Tests for the config flow."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.homeassistant_otel.const import (
    CONF_AUTH_HEADER,
    CONF_ENDPOINT,
    CONF_PROTOCOL,
    DOMAIN,
    PROTOCOL_GRPC,
)
from custom_components.homeassistant_otel.otlp import OtelConnectionError


@pytest.mark.parametrize(
    ("side_effect", "error_key"),
    [
        (OtelConnectionError("connection failed"), "cannot_connect"),
        (Exception("boom"), "unknown"),
    ],
)
async def test_user_step_validation_errors(
    hass: HomeAssistant,
    side_effect: Exception,
    error_key: str,
) -> None:
    """Test validation errors during the user config step."""
    with patch(
        "custom_components.homeassistant_otel.config_flow.validate_trace_exporter_connection",
        side_effect=side_effect,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_ENDPOINT: "http://localhost:4317",
                CONF_PROTOCOL: PROTOCOL_GRPC,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error_key}


async def test_user_step_success(hass: HomeAssistant) -> None:
    """Test successful config flow completion."""
    with patch(
        "custom_components.homeassistant_otel.config_flow.validate_trace_exporter_connection",
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_ENDPOINT: "http://localhost:4317",
                CONF_PROTOCOL: PROTOCOL_GRPC,
                CONF_AUTH_HEADER: "Bearer secret",
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "OpenTelemetry"
    assert result["data"] == {
        CONF_ENDPOINT: "http://localhost:4317",
        CONF_PROTOCOL: PROTOCOL_GRPC,
        CONF_AUTH_HEADER: "Bearer secret",
    }
