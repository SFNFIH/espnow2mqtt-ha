"""Shared entity base for ESP-NOW devices."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import (
    ATTR_CAPS,
    ATTR_HOP,
    ATTR_MAC,
    ATTR_NODE_ROLE,
    ATTR_VIA,
    DOMAIN,
)
from .hub import (
    SIGNAL_DEVICE_REMOVED,
    SIGNAL_DEVICE_UPDATED,
    EspNowDevice,
    EspNowHub,
)


@callback
def async_sync_device_registry(
    hass: HomeAssistant, identifier: str, **fields: Any
) -> None:
    """Push late-arriving device metadata into the device registry.

    `device_info` is only consulted the first time an entity is added, so
    anything the bridge tells us afterwards — the coordinator's firmware
    version, a model name that arrived with the second report — would otherwise
    never show up on the device page.
    """
    wanted = {key: value for key, value in fields.items() if value}
    if not wanted:
        return
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, identifier)})
    if device is None:
        return
    stale = {
        key: value for key, value in wanted.items() if getattr(device, key) != value
    }
    if stale:
        registry.async_update_device(device.id, **stale)


class EspNowEntity(Entity):
    """Base entity bound to one mesh device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    #: Capability that justifies this entity's existence. When the device stops
    #: advertising it the entity deletes itself instead of lingering with a
    #: frozen state. Diagnostic entities leave this as None: they apply to every
    #: node regardless of what it can do.
    _requires_cap: str | None = None

    def __init__(self, hub: EspNowHub, device: EspNowDevice, key: str) -> None:
        self._hub = hub
        self._device = device
        self._key = key
        self._purging = False
        self._attr_unique_id = f"{device.mac}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        dev = self._device
        connections = set()
        if ":" in dev.mac and not dev.is_placeholder:
            connections.add(("mac", dev.mac.lower()))
        return DeviceInfo(
            identifiers={(DOMAIN, dev.mac)},
            name=dev.name or dev.slug,
            manufacturer="espnow2mqtt",
            model=dev.model or "ESP-NOW node",
            via_device=(DOMAIN, "bridge"),
            connections=connections or None,
        )

    @property
    def available(self) -> bool:
        return self._hub.bridge_online and self._device.online

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        dev = self._device
        attrs: dict[str, Any] = {
            ATTR_MAC: None if dev.is_placeholder else dev.mac,
            ATTR_CAPS: list(dev.caps),
        }
        if dev.hop is not None:
            attrs[ATTR_HOP] = dev.hop
        if dev.via:
            attrs[ATTR_VIA] = dev.via
        if dev.node_role:
            attrs[ATTR_NODE_ROLE] = dev.node_role
        return attrs

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DEVICE_UPDATED, self._handle_update
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DEVICE_REMOVED, self._handle_device_removed
            )
        )

    @callback
    def _handle_update(self, entry_id: str, mac: str) -> None:
        if entry_id != self._hub.entry.entry_id or mac != self._device.mac:
            return
        self._device = self._hub.devices.get(mac, self._device)
        if self._is_stale():
            self._schedule_purge()
            return
        async_sync_device_registry(
            self.hass, self._device.mac, model=self._device.model
        )
        self.async_write_ha_state()

    @callback
    def _handle_device_removed(self, entry_id: str, mac: str) -> None:
        if entry_id != self._hub.entry.entry_id or mac != self._device.mac:
            return
        self._schedule_purge()

    def _is_stale(self) -> bool:
        # An empty caps list means "not known yet", not "supports nothing", so
        # never delete on the strength of it.
        return bool(
            self._requires_cap
            and self._device.caps
            and self._requires_cap not in self._device.caps
        )

    @callback
    def _schedule_purge(self) -> None:
        if self._purging:
            return
        self._purging = True
        self.hass.async_create_task(self._async_purge())

    async def _async_purge(self) -> None:
        """Delete this entity for good, so it can be recreated cleanly later."""
        if self._attr_unique_id:
            self._hub.discovered.discard(self._attr_unique_id)
        registry = er.async_get(self.hass)
        if self.entity_id and registry.async_get(self.entity_id):
            # Removing the registry entry also removes the entity from hass.
            registry.async_remove(self.entity_id)
        else:
            await self.async_remove(force_remove=True)
