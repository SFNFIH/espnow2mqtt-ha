"""Sensor platform — measurements + diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .discovery import async_setup_device_discovery
from .entity import EspNowEntity
from .hub import EspNowDevice, EspNowHub


@dataclass(frozen=True)
class SensorSpec:
    name: str
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    unit: str | None = None
    category: EntityCategory | None = None
    precision: int | None = None
    #: Measurements only exist if the device advertises them; diagnostics apply
    #: to every mesh node, so they have no capability gate.
    measurement: bool = False


SENSOR_SPECS: dict[str, SensorSpec] = {
    "temperature": SensorSpec(
        "Temperature",
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        UnitOfTemperature.CELSIUS,
        precision=1,
        measurement=True,
    ),
    "humidity": SensorSpec(
        "Humidity",
        SensorDeviceClass.HUMIDITY,
        SensorStateClass.MEASUREMENT,
        PERCENTAGE,
        precision=1,
        measurement=True,
    ),
    "pressure": SensorSpec(
        "Pressure",
        SensorDeviceClass.PRESSURE,
        SensorStateClass.MEASUREMENT,
        UnitOfPressure.HPA,
        precision=1,
        measurement=True,
    ),
    "illuminance": SensorSpec(
        "Illuminance",
        SensorDeviceClass.ILLUMINANCE,
        SensorStateClass.MEASUREMENT,
        LIGHT_LUX,
        precision=0,
        measurement=True,
    ),
    "power": SensorSpec(
        "Power",
        SensorDeviceClass.POWER,
        SensorStateClass.MEASUREMENT,
        UnitOfPower.WATT,
        precision=1,
        measurement=True,
    ),
    "energy": SensorSpec(
        "Energy",
        SensorDeviceClass.ENERGY,
        SensorStateClass.TOTAL_INCREASING,
        UnitOfEnergy.WATT_HOUR,
        precision=2,
        measurement=True,
    ),
    "hop": SensorSpec(
        "Mesh Hop",
        category=EntityCategory.DIAGNOSTIC,
        precision=0,
    ),
    "rssi": SensorSpec(
        "RSSI",
        SensorDeviceClass.SIGNAL_STRENGTH,
        unit="dBm",
        category=EntityCategory.DIAGNOSTIC,
        precision=0,
    ),
    "node_role": SensorSpec(
        "Node Role",
        category=EntityCategory.DIAGNOSTIC,
    ),
}

_MEASUREMENT_KEYS = tuple(k for k, s in SENSOR_SPECS.items() if s.measurement)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: EspNowHub = hass.data[DOMAIN][entry.entry_id]

    def _build(hub: EspNowHub, device: EspNowDevice) -> list[EspNowSensor]:
        wanted = {"hop", "node_role"}
        wanted.update(cap for cap in device.caps if cap in SENSOR_SPECS)
        if device.rssi is not None or "rssi" in device.state:
            wanted.add("rssi")
        return [EspNowSensor(hub, device, key) for key in sorted(wanted)]

    async_setup_device_discovery(hass, entry, hub, async_add_entities, _build)


class EspNowSensor(EspNowEntity, SensorEntity):
    """Generic numeric/text sensor."""

    def __init__(self, hub: EspNowHub, device: EspNowDevice, key: str) -> None:
        super().__init__(hub, device, key)
        spec = SENSOR_SPECS[key]
        self._attr_name = spec.name
        self._attr_device_class = spec.device_class
        self._attr_state_class = spec.state_class
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_entity_category = spec.category
        self._attr_suggested_display_precision = spec.precision
        if spec.measurement:
            self._requires_cap = key

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
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
