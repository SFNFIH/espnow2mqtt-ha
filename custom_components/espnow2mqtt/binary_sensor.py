"""Binary sensor platform — contact, occupancy, smoke, bridge."""

from __future__ import annotations

from typing import Any

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
from .discovery import async_setup_device_discovery
from .entity import EspNowEntity, async_sync_device_registry
from .hub import SIGNAL_BRIDGE_UPDATED, EspNowDevice, EspNowHub

BINARY_SPECS: dict[str, tuple[str, BinarySensorDeviceClass]] = {
    "contact": ("Contact", BinarySensorDeviceClass.DOOR),
    "occupancy": ("Occupancy", BinarySensorDeviceClass.OCCUPANCY),
    "motion": ("Motion", BinarySensorDeviceClass.MOTION),
    "smoke": ("Smoke", BinarySensorDeviceClass.SMOKE),
    "carbon_monoxide": ("Carbon Monoxide", BinarySensorDeviceClass.CO),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: EspNowHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([EspNowBridgeBinary(hub)])

    def _build(hub: EspNowHub, device: EspNowDevice) -> list[EspNowBinary]:
        return [
            EspNowBinary(hub, device, key, name, device_class)
            for key, (name, device_class) in BINARY_SPECS.items()
            if key in device.caps
        ]

    async_setup_device_discovery(hass, entry, hub, async_add_entities, _build)


class EspNowBridgeBinary(BinarySensorEntity):
    """USB bridge online status.

    Deliberately not an `EspNowEntity`: it reports on the bridge itself, so it
    must stay available even when the bridge is down — that is the whole point
    of it.
    """

    _attr_has_entity_name = True
    _attr_name = "Bridge"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_should_poll = False

    def __init__(self, hub: EspNowHub) -> None:
        self._hub = hub
        self._attr_unique_id = f"{hub.entry.entry_id}_bridge"

    @property
    def device_info(self) -> DeviceInfo:
        info = self._hub.bridge_info
        mac = str(info.get("mac") or "")
        connections = {("mac", mac.lower())} if ":" in mac else None
        return DeviceInfo(
            identifiers={(DOMAIN, "bridge")},
            name="ESP-NOW Coordinator",
            manufacturer="espnow2mqtt",
            model="USB Coordinator Bridge",
            sw_version=str(info["fw"]) if info.get("fw") else None,
            connections=connections,
        )

    @property
    def is_on(self) -> bool:
        return self._hub.bridge_online

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Everything the coordinator told us about itself.

        Sourced from the retained `bridge/info` topic, which carries the
        coordinator's own hello line: protocol version, Wi-Fi channel, firmware
        and MAC. Exposed here because there is nowhere else in HA to see it.
        """
        info = self._hub.bridge_info
        attrs: dict[str, Any] = {"base_topic": self._hub.base}
        for key in ("mac", "fw", "channel", "version", "role", "stack"):
            if info.get(key) is not None:
                attrs[key] = info[key]
        attrs["devices"] = len(self._hub.devices)
        return attrs

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_BRIDGE_UPDATED, self._on_bridge
            )
        )

    @callback
    def _on_bridge(self, entry_id: str) -> None:
        if entry_id != self._hub.entry.entry_id:
            return
        # This entity is created at setup, long before `bridge/info` arrives, so
        # the firmware version has to be written to the registry after the fact.
        info = self._hub.bridge_info
        async_sync_device_registry(
            self.hass,
            "bridge",
            sw_version=str(info["fw"]) if info.get("fw") else None,
        )
        self.async_write_ha_state()


class EspNowBinary(EspNowEntity, BinarySensorEntity):
    """Generic binary sensor from caps."""

    def __init__(
        self,
        hub: EspNowHub,
        device: EspNowDevice,
        key: str,
        name: str,
        device_class: BinarySensorDeviceClass,
    ) -> None:
        super().__init__(hub, device, key)
        self._attr_name = name
        self._attr_device_class = device_class
        self._requires_cap = key

    @property
    def is_on(self) -> bool:
        return str(self._device.state.get(self._key, "OFF")).upper() == "ON"
