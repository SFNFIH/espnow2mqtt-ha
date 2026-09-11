"""Switch platform — devices with cap `switch` (not `light`)."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .discovery import async_setup_device_discovery
from .entity import EspNowEntity
from .hub import EspNowDevice, EspNowHub


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: EspNowHub = hass.data[DOMAIN][entry.entry_id]

    def _build(hub: EspNowHub, device: EspNowDevice) -> list[EspNowSwitch]:
        if "switch" not in device.caps or "light" in device.caps:
            return []
        return [EspNowSwitch(hub, device)]

    async_setup_device_discovery(hass, entry, hub, async_add_entities, _build)


class EspNowSwitch(EspNowEntity, SwitchEntity):
    """MQTT-backed switch."""

    _attr_name = "Switch"
    # The hub drops `switch` from caps as soon as a device turns out to be a
    # light, which deletes this entity instead of leaving a duplicate behind.
    _requires_cap = "switch"

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "switch")

    @property
    def is_on(self) -> bool:
        return str(self._device.state.get("switch", "OFF")).upper() == "ON"

    async def async_turn_on(self, **kwargs) -> None:
        await self._hub.async_set_switch(self._device, "ON")

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.async_set_switch(self._device, "OFF")
