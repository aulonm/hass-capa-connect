"""The Capa Connect (Glen Dimplex / Noirot / GDHV) integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CapaAuth, CapaClient
from .const import DOMAIN
from .coordinator import CapaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    auth = CapaAuth(session, refresh_token=entry.data["refresh_token"])
    client = CapaClient(session, auth)
    coordinator = CapaCoordinator(hass, entry, client, auth)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    _async_remove_stale_devices(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Options (polling interval) take effect by reloading the entry.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


def _zone_id_of(device: dr.DeviceEntry) -> str | None:
    """The Capa Connect zone id a device was created for, if any."""
    for domain, identifier in device.identifiers:
        if domain == DOMAIN:
            return identifier
    return None


def _async_remove_stale_devices(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: CapaCoordinator
) -> None:
    """Drop devices for zones that no longer exist or no longer have heaters.

    Runs once per setup (HA start, reload, update), after a successful first
    refresh. A zone deleted or emptied in the Capa Connect app would otherwise
    leave a permanently unavailable device behind. If the cloud returned no
    zones at all, nothing is removed, so a bad response cannot wipe devices.
    """
    current = set(coordinator.data["zones"])
    if not current:
        return
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        zone_id = _zone_id_of(device)
        if zone_id is not None and zone_id not in current:
            _LOGGER.info(
                "Removing device %r: zone %s no longer has heaters in Capa Connect",
                device.name_by_user or device.name,
                zone_id,
            )
            registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow deleting a device from the UI, but only once its zone is gone.

    Deleting a device whose zone still exists would be undone at the next
    poll, so the delete button is refused for those.
    """
    coordinator: CapaCoordinator = entry.runtime_data
    return _zone_id_of(device) not in coordinator.data["zones"]


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
