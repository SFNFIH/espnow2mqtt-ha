"""Shared dynamic-discovery plumbing for every platform.

Devices are not known at setup time: they appear as MQTT messages arrive. Every
platform therefore does the same three things — react to the hub's update
signal, build the entities the device's capabilities justify, and skip the ones
it already created. Keeping that in one place means the bookkeeping set lives on
the hub, so an entity that deleted itself (because its capability went away) can
be created again if the capability comes back.
"""

from __future__ import annotations

from typing import Callable, Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .hub import SIGNAL_DEVICE_UPDATED, EspNowDevice, EspNowHub

#: Given a device, return the entities this platform wants for it. Called on
#: every update, so it must be cheap and free of side effects; entities whose
#: unique id already exists are dropped without ever reaching hass.
EntityBuilder = Callable[[EspNowHub, EspNowDevice], Iterable[Entity]]


@callback
def async_setup_device_discovery(
    hass: HomeAssistant,
    entry: ConfigEntry,
    hub: EspNowHub,
    async_add_entities: AddEntitiesCallback,
    build: EntityBuilder,
) -> None:
    @callback
    def _discover(entry_id: str, mac: str) -> None:
        if entry_id != entry.entry_id:
            return
        device = hub.devices.get(mac)
        if device is None:
            return
        fresh = [
            entity
            for entity in build(hub, device)
            if entity.unique_id and entity.unique_id not in hub.discovered
        ]
        if not fresh:
            return
        hub.discovered.update(entity.unique_id for entity in fresh)
        async_add_entities(fresh)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_UPDATED, _discover)
    )
    for mac in list(hub.devices):
        _discover(entry.entry_id, mac)
