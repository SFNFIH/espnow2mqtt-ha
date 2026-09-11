"""Binary sensor platform — contact, bridge connectivity."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import EspNowEntity
from .hub import SIGNAL_BRIDGE_UPDATED, SIGNAL_DEVICE_UPDATED, EspNowDevice, EspNowHub


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: EspNowHub = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    # Bridge connectivity entity
    async_add_entities([EspNowBridgeBinary(hub)])

    @callback
    def _discover(entry_id: str, mac: str) -> None:
        if entry_id != entry.entry_id:
            return
        dev = hub.devices.get(mac)
        if not dev:
            return
        if "contact" in dev.caps:
            uid = f"{mac}_contact"
            if uid not in known:
                known.add(uid)
                async_add_entities([EspNowContact(hub, dev)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_UPDATED, _discover)
    )
    for mac in list(hub.devices):
        _discover(entry.entry_id, mac)


class EspNowBridgeBinary(BinarySensorEntity):
    """USB bridge online status."""

    _attr_has_entity_name = True
    _attr_name = "Bridge"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_should_poll = False

    def __init__(self, hub: EspNowHub) -> None:
        self._hub = hub
        self._attr_unique_id = f"{hub.entry.entry_id}_bridge"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "bridge")},
            name="ESP-NOW Coordinator",
            manufacturer="espnow2mqtt",
            model="USB Coordinator Bridge",
        )

    @property
    def is_on(self) -> bool:
        return self._hub.bridge_online

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_BRIDGE_UPDATED, self._on_bridge
            )
        )

    @callback
    def _on_bridge(self, entry_id: str) -> None:
        if entry_id == self._hub.entry.entry_id:
            self.async_write_ha_state()


class EspNowContact(EspNowEntity, BinarySensorEntity):
    """Door/window contact."""

    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "contact")
        self._attr_name = "Contact"

    @property
    def is_on(self) -> bool:
        return str(self._device.state.get("contact", "OFF")).upper() == "ON"
