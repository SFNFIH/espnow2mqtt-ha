"""Device hub: tracks ESP-NOW nodes from MQTT and exposes entity helpers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    DOMAIN,
    TOPIC_BRIDGE_DEVICES,
    TOPIC_BRIDGE_STATE,
    TOPIC_PERMIT_JOIN,
)

_LOGGER = logging.getLogger(__name__)

SIGNAL_DEVICE_UPDATED = f"{DOMAIN}_device_updated"
SIGNAL_BRIDGE_UPDATED = f"{DOMAIN}_bridge_updated"


def slug_from_name_or_mac(name: str, mac: str) -> str:
    if name:
        return name.replace(" ", "_").lower()
    return mac.replace(":", "").lower()


@dataclass
class EspNowDevice:
    mac: str
    name: str = ""
    model: str = ""
    online: bool = False
    caps: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    hop: int | None = None
    via: str = ""
    node_role: str = ""
    rssi: int | None = None

    @property
    def slug(self) -> str:
        return slug_from_name_or_mac(self.name, self.mac)


class EspNowHub:
    """Central state for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, base_topic: str) -> None:
        self.hass = hass
        self.entry = entry
        self.base = base_topic.rstrip("/")
        self.devices: dict[str, EspNowDevice] = {}
        self.bridge_online = False
        self.bridge_info: dict[str, Any] = {}
        self._unsubs: list[Callable[[], None]] = []
        self._platforms_loaded = False

    async def async_start(self) -> None:
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass, f"{self.base}/{TOPIC_BRIDGE_STATE}", self._on_bridge_state, 0
            )
        )
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass, f"{self.base}/{TOPIC_BRIDGE_DEVICES}", self._on_devices, 0
            )
        )
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass, f"{self.base}/+/state", self._on_device_state, 0
            )
        )
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass, f"{self.base}/+/availability", self._on_availability, 0
            )
        )
        _LOGGER.info("ESP-NOW hub listening on %s/#", self.base)

    async def async_stop(self) -> None:
        while self._unsubs:
            unsub = self._unsubs.pop()
            unsub()

    @callback
    def _on_bridge_state(self, msg: mqtt.ReceiveMessage) -> None:
        payload = msg.payload
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="ignore")
        self.bridge_online = str(payload).strip().lower() == "online"
        async_dispatcher_send(self.hass, SIGNAL_BRIDGE_UPDATED, self.entry.entry_id)

    @callback
    def _on_devices(self, msg: mqtt.ReceiveMessage) -> None:
        raw = msg.payload
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        try:
            lst = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(lst, list):
            return
        for item in lst:
            if not isinstance(item, dict):
                continue
            mac = str(item.get("mac") or "")
            if not mac:
                continue
            dev = self.devices.get(mac) or EspNowDevice(mac=mac)
            if item.get("name"):
                dev.name = str(item["name"])
            if item.get("model"):
                dev.model = str(item["model"])
            if "online" in item:
                dev.online = bool(item["online"])
            if item.get("node_role"):
                dev.node_role = str(item["node_role"])
            if item.get("via"):
                dev.via = str(item["via"])
            if "hop" in item and item["hop"] is not None:
                try:
                    dev.hop = int(item["hop"])
                except (TypeError, ValueError):
                    pass
            if "rssi" in item and item["rssi"] is not None:
                try:
                    dev.rssi = int(item["rssi"])
                except (TypeError, ValueError):
                    pass
            self.devices[mac] = dev
            async_dispatcher_send(
                self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, mac
            )

    @callback
    def _on_availability(self, msg: mqtt.ReceiveMessage) -> None:
        # espnow2mqtt/<slug>/availability
        parts = msg.topic.split("/")
        if len(parts) < 3:
            return
        slug = parts[-2]
        raw = msg.payload
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        online = str(raw).strip().lower() == "online"
        for mac, dev in self.devices.items():
            if dev.slug == slug:
                dev.online = online
                async_dispatcher_send(
                    self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, mac
                )
                return

    @callback
    def _on_device_state(self, msg: mqtt.ReceiveMessage) -> None:
        parts = msg.topic.split("/")
        if len(parts) < 3 or parts[-1] != "state":
            return
        slug = parts[-2]
        if slug == "bridge":
            return
        raw = msg.payload
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return

        # Find by slug or create placeholder until devices list arrives
        mac = None
        for m, d in self.devices.items():
            if d.slug == slug:
                mac = m
                break
        if mac is None:
            # Synthesize mac-less device keyed by slug until list sync
            mac = f"slug:{slug}"
            self.devices[mac] = EspNowDevice(mac=mac, name=slug)

        dev = self.devices[mac]
        if not dev.name:
            dev.name = slug
        caps = payload.get("caps")
        if isinstance(caps, list):
            dev.caps = [str(c).lower() for c in caps]
        elif isinstance(caps, str) and caps:
            dev.caps = [c.strip().lower() for c in caps.split(",") if c.strip()]
        else:
            for key in ("temperature", "humidity", "switch", "contact", "power", "energy", "button"):
                if key in payload and key not in dev.caps:
                    dev.caps.append(key)
        if payload.get("node_role"):
            dev.node_role = str(payload["node_role"])
        if "hop" in payload:
            try:
                dev.hop = int(payload["hop"])
            except (TypeError, ValueError):
                pass
        if payload.get("via"):
            dev.via = str(payload["via"])
        merged = dict(dev.state)
        merged.update(payload)
        if "switch" in merged:
            sw = str(merged["switch"]).upper()
            merged["switch"] = "ON" if sw in ("ON", "1", "TRUE") else "OFF"
        if "contact" in merged:
            c = str(merged["contact"]).upper()
            merged["contact"] = "ON" if c in ("ON", "1", "TRUE", "OPEN") else "OFF"
        dev.state = merged
        dev.online = True
        async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, mac)

    async def async_permit_join(self, seconds: int = 60) -> None:
        seconds = max(1, min(300, int(seconds)))
        await mqtt.async_publish(
            self.hass, f"{self.base}/{TOPIC_PERMIT_JOIN}", str(seconds), 0, False
        )

    async def async_set_switch(self, device: EspNowDevice, value: str) -> None:
        payload = json.dumps({"switch": value})
        await mqtt.async_publish(
            self.hass, f"{self.base}/{device.slug}/set", payload, 0, False
        )
