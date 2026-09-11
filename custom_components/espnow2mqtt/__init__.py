"""ESP-NOW 2 MQTT Home Assistant integration — ESPHome-like, no YAML entities."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall

from .const import CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC, DOMAIN
from .hub import EspNowHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
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
