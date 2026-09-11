"""Diagnostics support for Capa Connect.

Settings → Devices & services → Capa Connect → ⋮ → *Download diagnostics*
produces a JSON file with the normalised zone state *and* the last raw API
payloads. Share it (it is redacted) when reporting a heater model that does
not behave as expected — it is the fastest way to see what the cloud returns
for that model.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import CapaCoordinator

TO_REDACT = {
    "refresh_token",
    "email",
    "Email",
    "UserName",
    "FirstName",
    "LastName",
    "PhoneNumber",
    "Address",
    "AddressLine1",
    "AddressLine2",
    "PostCode",
    "Postcode",
    "City",
    "Latitude",
    "Longitude",
    "MacAddress",
    "SerialNumber",
    "DeviceId",
    "serial",
    "PrimaryUserEmail",
    # BLE pairing identity + 6-digit pairing code of each heater.
    "BLEIdentifier",
    "SecurityCode",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: CapaCoordinator = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "data": async_redact_data(coordinator.data, TO_REDACT),
        },
        "raw_api": async_redact_data(coordinator.raw, TO_REDACT),
    }
