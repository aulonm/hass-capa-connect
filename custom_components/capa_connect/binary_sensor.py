"""Binary sensors for a Capa Connect heater zone."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CapaCoordinator
from .entity import CapaZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CapaCoordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for zone_id in coordinator.data["zones"]:
        entities.append(CapaConnectivity(coordinator, zone_id))
        entities.append(CapaControlsLock(coordinator, zone_id))
    async_add_entities(entities)


class CapaConnectivity(CapaZoneEntity, BinarySensorEntity):
    """Whether the zone's heater(s) are online with the GDHV cloud.

    The climate entity goes *unavailable* when the heater is offline; this sensor
    stays available and reports off, which is what automations and history need.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "connected"

    def __init__(self, coordinator: CapaCoordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id)
        self._attr_unique_id = f"{zone_id}_connected"

    @property
    def is_on(self) -> bool:
        return bool(self._zone.get("connected"))

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "heaters": [
                {
                    "name": a.get("name"),
                    "model": a.get("model"),
                    "firmware": a.get("firmware"),
                    "connected": a.get("connected"),
                    "updating_firmware": a.get("updating_firmware"),
                }
                for a in self._zone.get("appliances") or []
            ]
        }


class CapaControlsLock(CapaZoneEntity, BinarySensorEntity):
    """Child lock on the heater's own buttons, as set from the Capa Connect app.

    HA's LOCK device class reads *on = unlocked*, matching the app's meaning.
    Read-only for now: the API call the app uses to toggle it is not captured.
    """

    _attr_device_class = BinarySensorDeviceClass.LOCK
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "controls_lock"

    def __init__(self, coordinator: CapaCoordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id)
        self._attr_unique_id = f"{zone_id}_controls_lock"

    @property
    def is_on(self) -> bool:
        return not self._zone.get("locked")
