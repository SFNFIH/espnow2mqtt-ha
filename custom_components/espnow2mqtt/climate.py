"""Climate platform — Thermostat cluster."""

from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .discovery import async_setup_device_discovery
from .entity import EspNowEntity
from .hub import EspNowDevice, EspNowHub

#: Exactly the modes `en2m_hvac_mode_str()` can emit and `en2m_hvac_mode_parse()`
#: can accept. Advertising more would let HA send a mode the device silently
#: turns into "off".
_MODE_MAP = {
    "off": HVACMode.OFF,
    "auto": HVACMode.AUTO,
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
    "fan_only": HVACMode.FAN_ONLY,
}
_MODE_REV = {v: k for k, v in _MODE_MAP.items()}

#: What `turn_on` means for a thermostat that has no separate power switch.
_DEFAULT_ON_MODE = HVACMode.AUTO


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: EspNowHub = hass.data[DOMAIN][entry.entry_id]

    def _build(hub: EspNowHub, device: EspNowDevice) -> list[EspNowClimate]:
        if "climate" not in device.caps:
            return []
        return [EspNowClimate(hub, device)]

    async_setup_device_discovery(hass, entry, hub, async_add_entities, _build)


class EspNowClimate(EspNowEntity, ClimateEntity):
    """MQTT-backed thermostat."""

    _attr_name = "Thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = list(_MODE_MAP.values())
    _attr_min_temp = 5
    _attr_max_temp = 35
    _attr_target_temperature_step = 0.5
    _requires_cap = "climate"

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "climate")

    @property
    def hvac_mode(self) -> HVACMode | None:
        raw = self._device.state.get("hvac_mode")
        if raw is None:
            return None
        # An unrecognised mode used to be reported as "off", which is an active
        # lie about a running thermostat. Returning None shows it as unknown.
        return _MODE_MAP.get(str(raw).lower())

    @property
    def current_temperature(self) -> float | None:
        val = self._device.state.get(
            "current_temperature", self._device.state.get("temperature")
        )
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def target_temperature(self) -> float | None:
        val = self._device.state.get("target_temperature")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        mode = _MODE_REV.get(hvac_mode)
        if mode is None:
            return
        await self._hub.async_publish_set(self._device, {"hvac_mode": mode})

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(_DEFAULT_ON_MODE)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs) -> None:
        if ATTR_TEMPERATURE not in kwargs:
            return
        await self._hub.async_publish_set(
            self._device, {"target_temperature": float(kwargs[ATTR_TEMPERATURE])}
        )
