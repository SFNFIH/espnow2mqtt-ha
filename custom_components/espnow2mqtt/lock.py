"""Lock platform — DoorLock."""

from __future__ import annotations

from homeassistant.components.lock import LockEntity
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
        if not dev or "lock" not in dev.caps:
            return
        uid = f"{mac}_lock"
        if uid in known:
            return
        known.add(uid)
        async_add_entities([EspNowLock(hub, dev)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_UPDATED, _discover)
    )
    for mac in list(hub.devices):
        _discover(entry.entry_id, mac)


class EspNowLock(EspNowEntity, LockEntity):
    """MQTT-backed lock."""

    _attr_name = "Lock"

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "lock")

    @property
    def is_locked(self) -> bool:
        return str(self._device.state.get("lock", "UNLOCKED")).upper() == "LOCKED"

    async def async_lock(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"lock": "LOCK"})

    async def async_unlock(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"lock": "UNLOCK"})
