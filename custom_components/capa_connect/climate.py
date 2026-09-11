"""Climate entity for a Capa Connect heater zone."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_WHOLE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from .const import (
    HEATING_MODES,
    MAX_TEMP,
    MIN_TEMP,
    MODE_COMFORT,
    MODE_ECO,
    MODE_OFF,
    MODE_STANDBY,
    MODE_TO_PRESET,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_TO_MODE,
    TEMP_NONE,
    mode_label,
)
from .coordinator import CapaCoordinator
from .entity import CapaZoneEntity

PARALLEL_UPDATES = 1


def _round_half_up(value: float) -> int:
    """Round to the nearest whole degree, ties going up. Setpoints are always
    positive (MIN_TEMP..MAX_TEMP), so this is correct without a floor import."""
    return int(value + 0.5)


@dataclass
class _ResumeData(ExtraStoredData):
    """Mode + setpoint to resume when the heater is next turned on, persisted
    across restarts via RestoreEntity."""

    mode: int | None
    setpoint: int | None

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "setpoint": self.setpoint}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CapaCoordinator = entry.runtime_data
    async_add_entities(
        CapaClimate(coordinator, zone_id) for zone_id in coordinator.data["zones"]
    )


class CapaClimate(CapaZoneEntity, RestoreEntity, ClimateEntity):
    """One heater zone exposed as a HA climate entity."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = [PRESET_COMFORT, PRESET_ECO, PRESET_AWAY]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    # The heater only accepts whole degrees (it rounds 17.5 -> 18).
    _attr_target_temperature_step = PRECISION_WHOLE
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator: CapaCoordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id)
        self._attr_unique_id = zone_id
        # Remembered heating mode + setpoint so turning back on resumes them
        # rather than defaulting to the Comfort preset's stored temperature.
        self._resume_mode: int | None = None
        self._resume_setpoint: int | None = None

    def _snapshot_resume(self) -> None:
        # Remember the current heating mode + setpoint so a later turn-on resumes
        # it. Called from polls (covers off-outside-HA) and just before turn-off.
        z = self._zone
        if z.get("mode") in HEATING_MODES:
            self._resume_mode = z.get("mode")
            self._resume_setpoint = z.get("setpoint")

    def _handle_coordinator_update(self) -> None:
        self._snapshot_resume()
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Restore the resume state persisted before the last restart, so a
        # turn-on after a restart-while-off still resumes the right mode/temp.
        if (restored := await self.async_get_last_extra_data()) is not None:
            data = restored.as_dict()
            self._resume_mode = data.get("mode")
            self._resume_setpoint = data.get("setpoint")

    @property
    def extra_restore_state_data(self) -> _ResumeData:
        return _ResumeData(self._resume_mode, self._resume_setpoint)

    @property
    def available(self) -> bool:
        # Offline heaters can't be controlled, so the climate entity goes
        # unavailable; the connectivity binary sensor keeps reporting.
        return super().available and bool(self._zone.get("connected"))

    @property
    def current_temperature(self) -> float | None:
        return self._zone.get("room_temp")

    @property
    def target_temperature(self) -> float | None:
        z = self._zone
        mode = z.get("mode")
        if mode == MODE_OFF:
            return None
        # CurrentTemperature is the live setpoint (a per-zone override written by
        # UpdateZoneSetpointTemperature); 255 means "none — use the mode's stored
        # temp". Prefer it, then fall back to the Comfort/Eco stored setpoint.
        setpoint = z.get("setpoint")
        if isinstance(setpoint, (int, float)) and setpoint != TEMP_NONE:
            return setpoint
        if mode == MODE_COMFORT:
            return z.get("comfort")
        if mode == MODE_ECO:
            return z.get("eco")
        return None

    @property
    def _is_off(self) -> bool:
        # Hard off (mode 0) or standby (mode 13 = schedule suspended, shown as
        # "no heating" in the app). Both mean the heater is not maintaining heat.
        return self._zone.get("mode") in (MODE_OFF, MODE_STANDBY)

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.OFF if self._is_off else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction:
        if self._is_off:
            return HVACAction.OFF
        z = self._zone
        current = z.get("room_temp")
        target = self.target_temperature
        if current is not None and target is not None and current < target:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        return MODE_TO_PRESET.get(self._zone.get("mode"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # Diagnostics: the raw GDHV mode surfaces schedule (3/6) and
        # until-next-block (4/7) modes that aren't one of the four presets,
        # plus the active schedule name (e.g. "24 hour Off").
        z = self._zone
        return {
            "gdhv_mode": z.get("mode"),
            "gdhv_mode_label": mode_label(z.get("mode")),
            "schedule": z.get("schedule"),
            "site": z.get("site_name"),
            "heaters": len(z.get("appliances") or []),
            "controls_locked": z.get("locked"),
            "override_until": z.get("override_until"),
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        await self._write_setpoint(_round_half_up(temp))
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            self._snapshot_resume()
            await self._set_mode(MODE_OFF)
            return
        # Resume the pre-off mode + setpoint with a single reconciling refresh,
        # falling back to Comfort's stored temperature if no heating state was
        # ever observed.
        mode = self._resume_mode if self._resume_mode in HEATING_MODES else MODE_COMFORT
        await self._write_mode(mode)
        resume = self._resume_setpoint
        if isinstance(resume, int) and resume != TEMP_NONE:
            await self._write_setpoint(resume)
        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        mode = PRESET_TO_MODE.get(preset_mode)
        if mode is not None:
            await self._set_mode(mode)

    async def _set_mode(self, mode: int) -> None:
        await self._write_mode(mode)
        await self.coordinator.async_request_refresh()

    async def _write_mode(self, mode: int) -> None:
        # Write a mode without refreshing (the caller reconciles). TEMP_NONE keeps
        # the zone's stored Comfort/Eco setpoint and clears any live override.
        z = self._zone
        await self.coordinator.client.set_mode(
            z["site_id"], self._zone_id, mode, TEMP_NONE
        )
        self._apply_optimistic(mode=mode, setpoint=TEMP_NONE)

    async def _write_setpoint(self, temperature: int) -> None:
        # Write a live setpoint override without refreshing (caller reconciles).
        z = self._zone
        await self.coordinator.client.set_setpoint(
            z["site_id"], self._zone_id, temperature
        )
        self._apply_optimistic(setpoint=temperature)

    def _apply_optimistic(
        self, *, mode: int | None = None, setpoint: int | None = None
    ) -> None:
        """Reflect a just-sent change immediately in HA (and thus HomeKit, which
        listens to state changes) instead of waiting for the reconciling poll.
        The GDHV cloud is read-after-write consistent, so the follow-up refresh
        confirms these values rather than reverting them."""
        zone = self.coordinator.data["zones"].get(self._zone_id)
        if zone is None:
            return
        if mode is not None:
            zone["mode"] = mode
        if setpoint is not None:
            zone["setpoint"] = setpoint
        self.async_write_ha_state()
