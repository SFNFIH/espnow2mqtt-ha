"""Climate platform — Thermostat cluster."""

from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import EspNowEntity
from .hub import SIGNAL_DEVICE_UPDATED, EspNowDevice, EspNowHub

_MODE_MAP = {
    "off": HVACMode.OFF,
    "auto": HVACMode.AUTO,
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
    "fan_only": HVACMode.FAN_ONLY,
}
_MODE_REV = {v: k for k, v in _MODE_MAP.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: EspNowHub = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _discover(entry_id: str, mac: str) -> None:
        if entry_id != entry.entry_id:
            return
        dev = hub.devices.get(mac)
        if not dev or "climate" not in dev.caps:
            return
        uid = f"{mac}_climate"
        if uid in known:
            return
        known.add(uid)
        async_add_entities([EspNowClimate(hub, dev)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_UPDATED, _discover)
    )
    for mac in list(hub.devices):
        _discover(entry.entry_id, mac)


class EspNowClimate(EspNowEntity, ClimateEntity):
    """MQTT-backed thermostat."""

    _attr_name = "Thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = list(_MODE_MAP.values())
    _attr_min_temp = 5
    _attr_max_temp = 35
    _attr_target_temperature_step = 0.5

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "climate")

    @property
    def hvac_mode(self) -> HVACMode:
        raw = str(self._device.state.get("hvac_mode", "off")).lower()
        return _MODE_MAP.get(raw, HVACMode.OFF)

    @property
    def current_temperature(self) -> float | None:
        val = self._device.state.get("current_temperature", self._device.state.get("temperature"))
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
        mode = _MODE_REV.get(hvac_mode, "off")
        await self._hub.async_publish_set(self._device, {"hvac_mode": mode})

    async def async_set_temperature(self, **kwargs) -> None:
        if ATTR_TEMPERATURE not in kwargs:
            return
        await self._hub.async_publish_set(
            self._device, {"target_temperature": float(kwargs[ATTR_TEMPERATURE])}
        )
