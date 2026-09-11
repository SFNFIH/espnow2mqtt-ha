"""Light platform — OnOff + Level + optional color temperature."""

from __future__ import annotations

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import EspNowEntity
from .hub import SIGNAL_DEVICE_UPDATED, EspNowDevice, EspNowHub


def _mireds_to_kelvin(mireds: int) -> int:
    mireds = max(1, int(mireds))
    return int(round(1_000_000 / mireds))


def _kelvin_to_mireds(kelvin: int) -> int:
    kelvin = max(1, int(kelvin))
    return int(round(1_000_000 / kelvin))


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
        if not dev or "light" not in dev.caps:
            return
        uid = f"{mac}_light"
        if uid in known:
            return
        known.add(uid)
        async_add_entities([EspNowLight(hub, dev)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_UPDATED, _discover)
    )
    for mac in list(hub.devices):
        _discover(entry.entry_id, mac)


class EspNowLight(EspNowEntity, LightEntity):
    """Dimmable / CCT light."""

    _attr_name = "Light"
    _attr_min_color_temp_kelvin = 2000
    _attr_max_color_temp_kelvin = 6500

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "light")
        modes: set[ColorMode] = {ColorMode.BRIGHTNESS}
        if "color_temp" in device.state or "color_temp" in device.caps:
            modes = {ColorMode.COLOR_TEMP}
        self._attr_supported_color_modes = modes
        self._attr_color_mode = next(iter(modes))

    @property
    def is_on(self) -> bool:
        return str(self._device.state.get("switch", "OFF")).upper() == "ON"

    @property
    def brightness(self) -> int | None:
        raw = self._device.state.get("brightness", self._device.state.get("level"))
        if raw is None:
            return None
        try:
            level = int(raw)  # 0–254 Matter-like
        except (TypeError, ValueError):
            return None
        return max(0, min(255, int(round(level * 255 / 254)))) if level else 0

    @property
    def color_temp_kelvin(self) -> int | None:
        mireds = self._device.state.get("color_temp")
        if mireds is None:
            return None
        try:
            return _mireds_to_kelvin(int(mireds))
        except (TypeError, ValueError):
            return None

    async def async_turn_on(self, **kwargs) -> None:
        payload: dict = {"switch": "ON"}
        if ATTR_BRIGHTNESS in kwargs:
            bri = int(kwargs[ATTR_BRIGHTNESS])
            level = max(1, min(254, int(round(bri * 254 / 255))))
            payload["brightness"] = level
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            kelvin = int(kwargs[ATTR_COLOR_TEMP_KELVIN])
            payload["color_temp"] = _kelvin_to_mireds(kelvin)
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
        await self._hub.async_publish_set(self._device, payload)

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"switch": "OFF"})
