"""ESP-NOW 2 MQTT Home Assistant integration — ESPHome-like, no YAML entities."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC, DOMAIN
from .hub import SIGNAL_DEVICE_REMOVED, EspNowHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.LIGHT,
    Platform.FAN,
    Platform.COVER,
    Platform.LOCK,
    Platform.CLIMATE,
    Platform.EVENT,
]

SERVICE_PERMIT_JOIN = "permit_join"
ATTR_DURATION = "duration"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    base = entry.options.get(
        CONF_BASE_TOPIC, entry.data.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC)
    )
    hub = EspNowHub(hass, entry, base)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = hub
    await hub.async_start()

    @callback
    def _device_removed(entry_id: str, mac: str) -> None:
        """Drop a device that the hub folded into another one.

        Removing the device registry entry takes its entities with it, which is
        what we want for a `slug:` placeholder: every entity under it carried an
        unusable unique id.
        """
        if entry_id != entry.entry_id:
            return
        hub.discovered = {
            uid for uid in hub.discovered if not uid.startswith(f"{mac}_")
        }
        registry = dr.async_get(hass)
        device = registry.async_get_device(identifiers={(DOMAIN, mac)})
        if device and entry.entry_id in device.config_entries:
            _LOGGER.debug("removing stale device registry entry for %s", mac)
            registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_REMOVED, _device_removed)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _permit_join(call: ServiceCall) -> None:
        duration = int(call.data.get(ATTR_DURATION, 60))
        for h in hass.data[DOMAIN].values():
            if isinstance(h, EspNowHub):
                await h.async_permit_join(duration)

    if not hass.services.has_service(DOMAIN, SERVICE_PERMIT_JOIN):
        hass.services.async_register(
            DOMAIN,
            SERVICE_PERMIT_JOIN,
            _permit_join,
            schema=vol.Schema(
                {vol.Optional(ATTR_DURATION, default=60): vol.All(vol.Coerce(int), vol.Range(1, 300))}
            ),
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hub: EspNowHub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.async_stop()
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_PERMIT_JOIN)
            hass.data.pop(DOMAIN, None)
    return unload_ok
