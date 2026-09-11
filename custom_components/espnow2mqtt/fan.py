"""Fan platform — FanControl percentage + preset modes."""

from __future__ import annotations

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import EspNowEntity
from .hub import SIGNAL_DEVICE_UPDATED, EspNowDevice, EspNowHub

PRESET_MODES = ["off", "low", "medium", "high", "on", "auto", "smart"]


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
        if not dev or "fan" not in dev.caps:
            return
        uid = f"{mac}_fan"
        if uid in known:
            return
        known.add(uid)
        async_add_entities([EspNowFan(hub, dev)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_UPDATED, _discover)
    )
    for mac in list(hub.devices):
        _discover(entry.entry_id, mac)


class EspNowFan(EspNowEntity, FanEntity):
    """MQTT-backed fan."""

    _attr_name = "Fan"
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    _attr_preset_modes = PRESET_MODES
    _attr_speed_count = 100

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "fan")

    @property
    def is_on(self) -> bool:
        mode = str(self._device.state.get("fan_mode", "off")).lower()
        if mode in ("off", ""):
            return False
        if mode in ("on", "auto", "smart", "low", "medium", "high"):
            return True
        return (self.percentage or 0) > 0

    @property
    def percentage(self) -> int | None:
        raw = self._device.state.get("percentage")
        if raw is None:
            return None
        try:
            return max(0, min(100, int(raw)))
        except (TypeError, ValueError):
            return None

    @property
    def preset_mode(self) -> str | None:
        mode = str(self._device.state.get("fan_mode", "off")).lower()
        return mode if mode in PRESET_MODES else "off"

    async def async_turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs) -> None:
        payload: dict = {}
        if preset_mode:
            payload["fan_mode"] = preset_mode
        elif percentage is not None:
            payload["percentage"] = percentage
            payload["fan_mode"] = "on" if percentage else "off"
        else:
            payload["fan_mode"] = "on"
            payload["percentage"] = self.percentage or 50
        await self._hub.async_publish_set(self._device, payload)

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"fan_mode": "off", "percentage": 0})

    async def async_set_percentage(self, percentage: int) -> None:
        await self._hub.async_publish_set(
            self._device,
            {"percentage": percentage, "fan_mode": "off" if percentage == 0 else "on"},
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._hub.async_publish_set(self._device, {"fan_mode": preset_mode})
