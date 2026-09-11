"""Cover platform — WindowCovering position 0=open … 100=closed."""

from __future__ import annotations

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
)
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
        if not dev or "cover" not in dev.caps:
            return
        uid = f"{mac}_cover"
        if uid in known:
            return
        known.add(uid)
        async_add_entities([EspNowCover(hub, dev)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_UPDATED, _discover)
    )
    for mac in list(hub.devices):
        _discover(entry.entry_id, mac)


class EspNowCover(EspNowEntity, CoverEntity):
    """MQTT-backed cover."""

    _attr_name = "Cover"
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "cover")

    def _closed_pct(self) -> int:
        raw = self._device.state.get("position")
        try:
            return max(0, min(100, int(raw)))
        except (TypeError, ValueError):
            cover = str(self._device.state.get("cover", "OPEN")).upper()
            return 100 if cover == "CLOSED" else 0

    @property
    def current_cover_position(self) -> int | None:
        # HA: 0 = closed, 100 = open
        return 100 - self._closed_pct()

    @property
    def is_closed(self) -> bool:
        return self._closed_pct() >= 95

    async def async_open_cover(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"cover": "OPEN"})

    async def async_close_cover(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"cover": "CLOSE"})

    async def async_stop_cover(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"cover": "STOP"})

    async def async_set_cover_position(self, **kwargs) -> None:
        # kwargs position is HA open% → firmware closed%
        open_pct = int(kwargs.get("position", 0))
        closed = max(0, min(100, 100 - open_pct))
        await self._hub.async_publish_set(self._device, {"position": closed})
