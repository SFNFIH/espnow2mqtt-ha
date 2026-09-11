"""Light platform — OnOff + Level + optional color temperature."""

from __future__ import annotations

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .discovery import async_setup_device_discovery
from .entity import EspNowEntity
from .hub import EspNowDevice, EspNowHub


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

    def _build(hub: EspNowHub, device: EspNowDevice) -> list[EspNowLight]:
        if "light" not in device.caps:
            return []
        return [EspNowLight(hub, device)]

    async_setup_device_discovery(hass, entry, hub, async_add_entities, _build)


class EspNowLight(EspNowEntity, LightEntity):
    """Dimmable / CCT light."""

    _attr_name = "Light"
    _attr_min_color_temp_kelvin = 2000
    _attr_max_color_temp_kelvin = 6500
    _requires_cap = "light"

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "light")

    def _is_cct(self) -> bool:
        """Whether this bulb has shown any sign of colour-temperature support.

        Resolved on every read rather than once in the constructor: a bulb that
        was created from a report which happened not to carry `color_temp` used
        to be stuck as a plain dimmer for the lifetime of the entity, even after
        later reports proved otherwise.
        """
        return (
            "color_temp" in self._device.state
            or "color_temp" in self._device.caps
            or str(self._device.state.get("color_mode", "")).lower() == "color_temp"
        )

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        # COLOR_TEMP already implies brightness, and HA rejects a set that pairs
        # BRIGHTNESS with a richer mode, so this is one or the other.
        return {ColorMode.COLOR_TEMP} if self._is_cct() else {ColorMode.BRIGHTNESS}

    @property
    def color_mode(self) -> ColorMode:
        return ColorMode.COLOR_TEMP if self._is_cct() else ColorMode.BRIGHTNESS

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
        await self._hub.async_publish_set(self._device, payload)

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"switch": "OFF"})
