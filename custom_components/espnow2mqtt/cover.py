"""Cover platform — WindowCovering position 0=open … 100=closed."""

from __future__ import annotations

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverEntity,
    CoverEntityFeature,
)
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

    def _build(hub: EspNowHub, device: EspNowDevice) -> list[EspNowCover]:
        if "cover" not in device.caps:
            return []
        return [EspNowCover(hub, device)]

    async_setup_device_discovery(hass, entry, hub, async_add_entities, _build)


class EspNowCover(EspNowEntity, CoverEntity):
    """MQTT-backed cover.

    The firmware follows Matter's `CurrentPositionLiftPercentage`, where 0 is
    fully open and 100 is fully closed. HA uses the opposite convention, so
    every position crossing this class is inverted.
    """

    _attr_name = "Cover"
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )
    _requires_cap = "cover"

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "cover")

    def _closed_pct(self) -> int | None:
        raw = self._device.state.get("position")
        try:
            return max(0, min(100, int(raw)))
        except (TypeError, ValueError):
            pass
        # A cover that only reports the coarse OPEN/CLOSED string still gets a
        # usable position, just a two-valued one.
        cover = str(self._device.state.get("cover", "")).upper()
        if cover == "CLOSED":
            return 100
        if cover == "OPEN":
            return 0
        return None

    @property
    def current_cover_position(self) -> int | None:
        closed = self._closed_pct()
        return None if closed is None else 100 - closed

    @property
    def is_closed(self) -> bool | None:
        # The device decides when it counts as shut — the firmware publishes the
        # verdict alongside the raw position. Only guess from the position when
        # it stayed silent, rather than applying a threshold of our own that
        # could contradict it.
        cover = str(self._device.state.get("cover", "")).upper()
        if cover in ("OPEN", "CLOSED"):
            return cover == "CLOSED"
        position = self.current_cover_position
        return None if position is None else position == 0

    async def async_open_cover(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"cover": "OPEN"})

    async def async_close_cover(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"cover": "CLOSE"})

    async def async_stop_cover(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"cover": "STOP"})

    async def async_set_cover_position(self, **kwargs) -> None:
        open_pct = max(0, min(100, int(kwargs.get(ATTR_POSITION, 0))))
        await self._hub.async_publish_set(self._device, {"position": 100 - open_pct})
