"""Event platform — momentary inputs reported under the `button` capability.

A button press has no state to hold: by the time HA hears about it, it is over.
Modelling it as a sensor would leave a value stuck at the last press forever, so
it becomes an event entity instead, which records *when* something happened and
which kind of press it was.

The `button` capability previously reached the hub and stopped there, because no
platform claimed it — a device advertising it produced no entity at all.

Because `<slug>/state` is retained and repeats every field on every report, a
press can only be recognised as a *change* of the `button` value. Two identical
consecutive values are indistinguishable from one report being resent, so a
device that wants every press counted should report `button` as a counter that
increments on each press, and optionally `button_action` for the kind of press:

    {"button": 7, "button_action": "double_press"}
"""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .discovery import async_setup_device_discovery
from .entity import EspNowEntity
from .hub import EspNowDevice, EspNowHub

#: Press kinds published as distinct event types. Anything else a device sends
#: is folded into `press`, so an unknown spelling still fires something.
EVENT_TYPES = ["press", "double_press", "long_press", "release"]

_ALIASES = {
    "single": "press",
    "single_press": "press",
    "click": "press",
    "pressed": "press",
    "short": "press",
    "short_press": "press",
    "double": "double_press",
    "double_click": "double_press",
    "hold": "long_press",
    "long": "long_press",
    "held": "long_press",
    "released": "release",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: EspNowHub = hass.data[DOMAIN][entry.entry_id]

    def _build(hub: EspNowHub, device: EspNowDevice) -> list[EspNowButtonEvent]:
        if "button" not in device.caps:
            return []
        return [EspNowButtonEvent(hub, device)]

    async_setup_device_discovery(hass, entry, hub, async_add_entities, _build)


class EspNowButtonEvent(EspNowEntity, EventEntity):
    """Fires whenever the device reports a new `button` value."""

    _attr_name = "Button"
    _attr_event_types = EVENT_TYPES
    _requires_cap = "button"

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "button")
        self._last = self._fingerprint()

    def _fingerprint(self) -> tuple:
        state = self._device.state
        return (state.get("button"), state.get("button_action"))

    @callback
    def _handle_update(self, entry_id: str, mac: str) -> None:
        if entry_id != self._hub.entry.entry_id or mac != self._device.mac:
            return
        self._device = self._hub.devices.get(mac, self._device)
        if self._is_stale():
            self._schedule_purge()
            return
        current = self._fingerprint()
        if current != self._last and current[0] is not None:
            self._last = current
            self._trigger_event(
                self._event_type(current[1] if current[1] is not None else current[0]),
                {"value": current[0], "action": current[1]},
            )
        self.async_write_ha_state()

    @staticmethod
    def _event_type(raw: object) -> str:
        value = _ALIASES.get(str(raw).strip().lower(), str(raw).strip().lower())
        return value if value in EVENT_TYPES else "press"
