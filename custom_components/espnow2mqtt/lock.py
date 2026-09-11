"""Lock platform — DoorLock."""

from __future__ import annotations

from homeassistant.components.lock import LockEntity
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

    def _build(hub: EspNowHub, device: EspNowDevice) -> list[EspNowLock]:
        if "lock" not in device.caps:
            return []
        return [EspNowLock(hub, device)]

    async_setup_device_discovery(hass, entry, hub, async_add_entities, _build)


class EspNowLock(EspNowEntity, LockEntity):
    """MQTT-backed lock."""

    _attr_name = "Lock"
    _requires_cap = "lock"

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "lock")

    @property
    def is_locked(self) -> bool | None:
        raw = self._device.state.get("lock")
        if raw is None:
            return None
        return str(raw).upper() == "LOCKED"

    async def async_lock(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"lock": "LOCK"})

    async def async_unlock(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"lock": "UNLOCK"})
