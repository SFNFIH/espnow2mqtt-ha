"""Binary sensor platform — contact, occupancy, smoke, bridge."""

from __future__ import annotations

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
from .entity import EspNowEntity
from .hub import SIGNAL_BRIDGE_UPDATED, SIGNAL_DEVICE_UPDATED, EspNowDevice, EspNowHub

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
    known: set[str] = set()

    async_add_entities([EspNowBridgeBinary(hub)])

    @callback
    def _discover(entry_id: str, mac: str) -> None:
        if entry_id != entry.entry_id:
            return
        dev = hub.devices.get(mac)
        if not dev:
            return
        entities: list[EspNowBinary] = []
        for key, (name, device_class) in BINARY_SPECS.items():
            if key not in dev.caps:
                continue
            uid = f"{mac}_{key}"
            if uid in known:
                continue
            known.add(uid)
            entities.append(EspNowBinary(hub, dev, key, name, device_class))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_UPDATED, _discover)
    )
    for mac in list(hub.devices):
        _discover(entry.entry_id, mac)


class EspNowBridgeBinary(BinarySensorEntity):
    """USB bridge online status."""

    _attr_has_entity_name = True
    _attr_name = "Bridge"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_should_poll = False

    def __init__(self, hub: EspNowHub) -> None:
        self._hub = hub
        self._attr_unique_id = f"{hub.entry.entry_id}_bridge"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "bridge")},
            name="ESP-NOW Coordinator",
            manufacturer="espnow2mqtt",
            model="USB Coordinator Bridge",
        )

    @property
    def is_on(self) -> bool:
        return self._hub.bridge_online

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_BRIDGE_UPDATED, self._on_bridge
            )
        )

    @callback
    def _on_bridge(self, entry_id: str) -> None:
        if entry_id == self._hub.entry.entry_id:
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

    @property
    def is_on(self) -> bool:
        return str(self._device.state.get(self._key, "OFF")).upper() == "ON"
