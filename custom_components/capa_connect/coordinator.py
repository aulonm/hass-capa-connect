"""DataUpdateCoordinator for Capa Connect: polls the cloud for zone state."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CapaApiError, CapaAuth, CapaAuthError, CapaClient
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def scan_interval_for(entry: ConfigEntry) -> int:
    """Polling interval in seconds from the entry's options, clamped to bounds."""
    raw = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_SCAN_INTERVAL
    return max(MIN_SCAN_INTERVAL, min(MAX_SCAN_INTERVAL, value))


def _appliance_summary(
    app: dict[str, Any], room_temps: dict[str, Any]
) -> dict[str, Any]:
    """Normalise one DirectAppliance record into the fields entities use."""
    appliance_id = app.get("Id")
    return {
        "id": appliance_id,
        "name": app.get("FriendlyName"),
        "model": app.get("ProductModelName"),
        "firmware": app.get("FirmwareVersion"),
        "serial": app.get("SerialNumber") or app.get("DeviceId"),
        "product_type": app.get("ProductTypeName"),
        "series": app.get("SeriesIdentifier"),
        "connected": bool(app.get("IsConnected", False)),
        "room_temp": room_temps.get(appliance_id) if appliance_id else None,
        "updating_firmware": bool(app.get("CouldBeUpdatingFirmware", False)),
    }


class CapaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches every zone's state across the account each poll.

    ``data`` is ``{"zones": {zone_id: {...}}, "sites": {site_id: {...}}}``.
    Because Azure B2C rotates the refresh token on every use, the freshest token
    is written back into the config entry after each successful poll.

    The last raw API payloads are kept on ``raw`` (outside ``data``) so the
    diagnostics download shows exactly what the cloud returned. That is the
    main tool for adding support for heater models the integration has not
    been tested against.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: CapaClient,
        auth: CapaAuth,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval_for(entry)),
        )
        self.client = client
        self.auth = auth
        self.raw: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "sites": None,
            "zones": {},
            "room_temps": {},
            "zone_details": {},
        }
        try:
            zones: dict[str, Any] = {}
            sites: dict[str, Any] = {}
            site_list = await self.client.get_sites()
            raw["sites"] = site_list
            for site in site_list:
                site_id = site["Id"]
                sites[site_id] = {"id": site_id, "name": site.get("Name")}
                # room temps and the zone list are independent; the per-zone
                # detail fetches are independent of each other — fetch concurrently.
                temps, zone_list = await asyncio.gather(
                    self.client.get_room_temps(site_id),
                    self.client.get_zones(site_id),
                )
                raw["room_temps"][site_id] = temps
                raw["zones"][site_id] = zone_list
                details = await asyncio.gather(
                    *(self.client.get_zone(z["Id"], site_id) for z in zone_list)
                )
                for z, detail in zip(zone_list, details):
                    raw["zone_details"][z["Id"]] = detail
                    setting = detail.get("DirectZoneSetting") or {}
                    appliances = [
                        _appliance_summary(a, temps)
                        for a in (detail.get("DirectAppliances") or [])
                    ]
                    if not appliances:
                        # The app lets you create zones before assigning heaters
                        # to them. Nothing to control or measure, so skip them
                        # rather than creating permanently-unavailable entities.
                        _LOGGER.debug(
                            "Skipping zone %r (%s): no heaters assigned",
                            z.get("ZoneName"),
                            z["Id"],
                        )
                        continue
                    primary = appliances[0]
                    room_temps = [
                        a["room_temp"]
                        for a in appliances
                        if isinstance(a.get("room_temp"), (int, float))
                    ]
                    zones[z["Id"]] = {
                        "site_id": site_id,
                        "site_name": site.get("Name"),
                        "name": z.get("ZoneName") or primary.get("name"),
                        "mode": setting.get("CurrentMode"),
                        "setpoint": setting.get("CurrentTemperature"),
                        "comfort": setting.get("ComfortTemp"),
                        "eco": setting.get("EcoTemp"),
                        # Zone temperature = mean of its heaters' room sensors.
                        "room_temp": (
                            round(sum(room_temps) / len(room_temps), 1)
                            if room_temps
                            else None
                        ),
                        # A zone is reachable when at least one heater is online.
                        "connected": any(a["connected"] for a in appliances),
                        "appliance_id": primary.get("id"),
                        "model": primary.get("model"),
                        "product_type": primary.get("product_type"),
                        "firmware": primary.get("firmware"),
                        "appliances": appliances,
                        # LockStatus != 0 means the heater's own buttons are
                        # locked (child lock) from the app.
                        "locked": bool(setting.get("LockStatus") or 0),
                        "override_until": setting.get("OverrideDateTo"),
                        "schedule": (setting.get("DirectSchedule") or {}).get(
                            "ScheduleName"
                        ),
                        "schedule_id": setting.get("ScheduleId"),
                    }
        except CapaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CapaApiError as err:
            raise UpdateFailed(str(err)) from err

        self.raw = raw
        self._persist_rotated_token()
        return {"zones": zones, "sites": sites}

    def _persist_rotated_token(self) -> None:
        token = self.auth.refresh_token
        entry = self.config_entry
        if entry and token and token != entry.data.get("refresh_token"):
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, "refresh_token": token}
            )
