"""Sensors for a Capa Connect heater zone."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import MODE_LABELS, TEMP_NONE, mode_label
from .coordinator import CapaCoordinator
from .entity import CapaZoneEntity


def _temp(value: Any) -> float | None:
    """A GDHV temperature field, or None for the 255 "no setpoint" sentinel."""
    if isinstance(value, (int, float)) and value != TEMP_NONE:
        return value
    return None


@dataclass(frozen=True, kw_only=True)
class CapaSensorDescription(SensorEntityDescription):
    """Sensor description with a value extractor over the zone dict."""

    value_fn: Callable[[dict[str, Any]], Any]


ZONE_SENSORS: tuple[CapaSensorDescription, ...] = (
    CapaSensorDescription(
        key="room_temperature",
        translation_key="room_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda z: z.get("room_temp"),
    ),
    CapaSensorDescription(
        key="comfort_temperature",
        translation_key="comfort_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda z: _temp(z.get("comfort")),
    ),
    CapaSensorDescription(
        key="eco_temperature",
        translation_key="eco_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda z: _temp(z.get("eco")),
    ),
    CapaSensorDescription(
        key="gdhv_mode",
        translation_key="gdhv_mode",
        device_class=SensorDeviceClass.ENUM,
        options=sorted(MODE_LABELS.values()),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda z: mode_label(z.get("mode")),
    ),
    CapaSensorDescription(
        key="schedule",
        translation_key="schedule",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda z: z.get("schedule"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CapaCoordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for zone_id, zone in coordinator.data["zones"].items():
        entities.extend(
            CapaZoneSensor(coordinator, zone_id, desc) for desc in ZONE_SENSORS
        )
        # A zone with several heaters gets one temperature sensor per heater in
        # addition to the zone mean, so each unit's own reading is visible.
        appliances = zone.get("appliances") or []
        if len(appliances) > 1:
            entities.extend(
                CapaApplianceTemperature(coordinator, zone_id, a["id"], a.get("name"))
                for a in appliances
                if a.get("id")
            )
    async_add_entities(entities)


class CapaZoneSensor(CapaZoneEntity, SensorEntity):
    """One zone-level value."""

    entity_description: CapaSensorDescription

    def __init__(
        self,
        coordinator: CapaCoordinator,
        zone_id: str,
        description: CapaSensorDescription,
    ) -> None:
        super().__init__(coordinator, zone_id)
        self.entity_description = description
        self._attr_unique_id = f"{zone_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value_fn(self._zone)
        # ENUM sensors must only report values from ``options``; an unseen raw
        # mode is surfaced via the attribute below instead of breaking the entity.
        if (
            self.entity_description.device_class == SensorDeviceClass.ENUM
            and value not in (self.entity_description.options or ())
        ):
            return None
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "gdhv_mode":
            return {"raw_mode": self._zone.get("mode")}
        return None


class CapaApplianceTemperature(CapaZoneEntity, SensorEntity):
    """Room temperature reported by one specific heater in a multi-heater zone."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_translation_key = "appliance_temperature"

    def __init__(
        self,
        coordinator: CapaCoordinator,
        zone_id: str,
        appliance_id: str,
        appliance_name: str | None,
    ) -> None:
        super().__init__(coordinator, zone_id)
        self._appliance_id = appliance_id
        self._attr_unique_id = f"{appliance_id}_room_temperature"
        self._attr_translation_placeholders = {"name": appliance_name or appliance_id}

    def _appliance(self) -> dict[str, Any]:
        for a in self._zone.get("appliances") or []:
            if a.get("id") == self._appliance_id:
                return a
        return {}

    @property
    def available(self) -> bool:
        return super().available and bool(self._appliance().get("connected"))

    @property
    def native_value(self) -> float | None:
        return self._appliance().get("room_temp")
