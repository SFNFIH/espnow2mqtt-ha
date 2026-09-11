"""Switch platform — created for devices with cap `switch`."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import EspNowEntity
from .hub import SIGNAL_DEVICE_UPDATED, EspNowDevice, EspNowHub


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
        if not dev or "switch" not in dev.caps:
            return
        uid = f"{mac}_switch"
        if uid in known:
            return
        known.add(uid)
        async_add_entities([EspNowSwitch(hub, dev)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_UPDATED, _discover)
    )
    for mac in list(hub.devices):
        _discover(entry.entry_id, mac)


class EspNowSwitch(EspNowEntity, SwitchEntity):
    """MQTT-backed switch."""

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "switch")
        self._attr_name = "Switch"

    @property
    def is_on(self) -> bool:
        return str(self._device.state.get("switch", "OFF")).upper() == "ON"

    async def async_turn_on(self, **kwargs) -> None:
        await self._hub.async_set_switch(self._device, "ON")

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.async_set_switch(self._device, "OFF")
