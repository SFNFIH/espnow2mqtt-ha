"""Sensor platform — measurements + diagnostics."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import EspNowEntity
from .hub import SIGNAL_DEVICE_UPDATED, EspNowDevice, EspNowHub

# key -> (name, device_class, state_class, unit, entity_category, precision)
SENSOR_SPECS: dict[str, tuple] = {
    "temperature": (
        "Temperature",
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        UnitOfTemperature.CELSIUS,
        None,
        1,
    ),
    "humidity": (
        "Humidity",
        SensorDeviceClass.HUMIDITY,
        SensorStateClass.MEASUREMENT,
        PERCENTAGE,
        None,
        1,
    ),
    "pressure": (
        "Pressure",
        SensorDeviceClass.PRESSURE,
        SensorStateClass.MEASUREMENT,
        UnitOfPressure.HPA,
        None,
        1,
    ),
    "illuminance": (
        "Illuminance",
        SensorDeviceClass.ILLUMINANCE,
        SensorStateClass.MEASUREMENT,
        LIGHT_LUX,
        None,
        0,
    ),
    "power": (
        "Power",
        SensorDeviceClass.POWER,
        SensorStateClass.MEASUREMENT,
        UnitOfPower.WATT,
        None,
        1,
    ),
    "energy": (
        "Energy",
        SensorDeviceClass.ENERGY,
        SensorStateClass.TOTAL_INCREASING,
        UnitOfEnergy.WATT_HOUR,
        None,
        2,
    ),
    "hop": (
        "Mesh Hop",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        0,
    ),
    "rssi": (
        "RSSI",
        SensorDeviceClass.SIGNAL_STRENGTH,
        None,
        "dBm",
        EntityCategory.DIAGNOSTIC,
        0,
    ),
    "node_role": (
        "Node Role",
        None,
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        None,
    ),
}

_MEASUREMENT_KEYS = ("temperature", "humidity", "pressure", "illuminance", "power", "energy")


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
        if not dev:
            return
        wanted = set(dev.caps) | {"hop", "node_role"}
        if dev.rssi is not None or "rssi" in dev.state:
            wanted.add("rssi")
        entities: list[EspNowSensor] = []
        for key in wanted:
            if key not in SENSOR_SPECS:
                continue
            if key in _MEASUREMENT_KEYS and key not in dev.caps:
                continue
            uid = f"{mac}_{key}"
            if uid in known:
                continue
            known.add(uid)
            entities.append(EspNowSensor(hub, dev, key))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_UPDATED, _discover)
    )
    for mac in list(hub.devices):
        _discover(entry.entry_id, mac)


class EspNowSensor(EspNowEntity, SensorEntity):
    """Generic numeric/text sensor."""

    def __init__(self, hub: EspNowHub, device: EspNowDevice, key: str) -> None:
        super().__init__(hub, device, key)
        name, device_class, state_class, unit, category, _prec = SENSOR_SPECS[key]
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit
        self._attr_entity_category = category

    @property
    def native_value(self):
        key = self._key
        if key == "rssi":
            return self._device.rssi if self._device.rssi is not None else self._device.state.get("rssi")
        if key == "hop":
            return self._device.hop if self._device.hop is not None else self._device.state.get("hop")
        if key == "node_role":
            return self._device.node_role or self._device.state.get("node_role")
        val = self._device.state.get(key)
        if val is None:
            return None
        if key in _MEASUREMENT_KEYS:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
        return val
