"""Shared entity base for ESP-NOW devices."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .hub import SIGNAL_DEVICE_UPDATED, EspNowDevice, EspNowHub


class EspNowEntity(Entity):
    """Base entity bound to one mesh device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: EspNowHub, device: EspNowDevice, key: str) -> None:
        self._hub = hub
        self._device = device
        self._key = key
        self._attr_unique_id = f"{device.mac}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        dev = self._device
        name = dev.name or dev.slug
        connections = set()
        if ":" in dev.mac and not dev.mac.startswith("slug:"):
            connections.add(("mac", dev.mac.lower()))
        return DeviceInfo(
            identifiers={(DOMAIN, dev.mac)},
            name=name,
            manufacturer="espnow2mqtt",
            model=dev.model or "ESP-NOW node",
            via_device=(DOMAIN, "bridge"),
            connections=connections or None,
        )

    @property
    def available(self) -> bool:
        return self._hub.bridge_online and self._device.online

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATED,
                self._handle_update,
            )
        )

    def _handle_update(self, entry_id: str, mac: str) -> None:
        if entry_id != self._hub.entry.entry_id:
            return
        if mac != self._device.mac and mac in self._hub.devices:
            # refresh pointer if hub replaced object
            self._device = self._hub.devices.get(self._device.mac, self._device)
        if mac == self._device.mac:
            self.async_write_ha_state()
