"""Shared base classes for Capa Connect entities."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, manufacturer_for
from .coordinator import CapaCoordinator


class CapaZoneEntity(CoordinatorEntity[CapaCoordinator]):
    """An entity that belongs to one heater zone.

    All entities of a zone (climate, sensors, binary sensors) attach to the same
    HA device, identified by the zone id, so they show up together in the UI.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: CapaCoordinator, zone_id: str) -> None:
        super().__init__(coordinator)
        self._zone_id = zone_id

    @property
    def _zone(self) -> dict[str, Any]:
        return self.coordinator.data["zones"].get(self._zone_id, {})

    @property
    def device_info(self) -> DeviceInfo:
        z = self._zone
        appliances = z.get("appliances") or []
        serials = [a.get("serial") for a in appliances if a.get("serial")]
        return DeviceInfo(
            identifiers={(DOMAIN, self._zone_id)},
            name=z.get("name"),
            manufacturer=manufacturer_for(z.get("model"), z.get("product_type")),
            model=z.get("model"),
            sw_version=z.get("firmware"),
            serial_number=serials[0] if len(serials) == 1 else None,
            # Deliberately no suggested_area: HA (2026.x) builds entity IDs as
            # "<area> <device> <entity>", and since zones are named after rooms
            # a suggested area equal to the device name yields IDs like
            # climate.kontor_kontor. Users assign areas themselves instead.
        )

    @property
    def available(self) -> bool:
        return super().available and self._zone_id in self.coordinator.data["zones"]
