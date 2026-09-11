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
    EVENT_COMMAND_FAILED,
    TOPIC_BRIDGE_DEVICES,
    TOPIC_BRIDGE_INFO,
    TOPIC_BRIDGE_STATE,
    TOPIC_PERMIT_JOIN,
    TOPIC_SUFFIX_COMMAND_RESULT,
)

_LOGGER = logging.getLogger(__name__)

SIGNAL_DEVICE_UPDATED = f"{DOMAIN}_device_updated"
SIGNAL_DEVICE_REMOVED = f"{DOMAIN}_device_removed"
SIGNAL_BRIDGE_UPDATED = f"{DOMAIN}_bridge_updated"

#: State payload key -> capability it implies.
#:
#: Most keys are their own capability. The rest are *value* keys that only make
#: sense for one platform, so seeing them is enough to infer that platform. This
#: single table is the whole level-3 inference: an earlier version kept the key
#: list and the key->cap mapping separate, which let three mappings rot into
#: dead code because their keys were missing from the list.
_CAP_FROM_STATE_KEY: dict[str, str] = {
    "temperature": "temperature",
    "humidity": "humidity",
    "pressure": "pressure",
    "illuminance": "illuminance",
    "power": "power",
    "energy": "energy",
    "switch": "switch",
    "light": "light",
    "contact": "contact",
    "occupancy": "occupancy",
    "motion": "motion",
    "smoke": "smoke",
    "carbon_monoxide": "carbon_monoxide",
    "fan": "fan",
    "cover": "cover",
    "lock": "lock",
    "climate": "climate",
    "button": "button",
    "button_action": "button",
    "brightness": "light",
    "level": "light",
    "color_temp": "light",
    "color_mode": "light",
    "percentage": "fan",
    "fan_mode": "fan",
    "position": "cover",
    "hvac_mode": "climate",
    "target_temperature": "climate",
    "current_temperature": "climate",
}

#: Keys whose value the bridge may send in any of several spellings.
_BINARY_KEYS = ("contact", "occupancy", "motion", "smoke", "carbon_monoxide")
_BINARY_TRUE = ("ON", "1", "TRUE", "OPEN", "DETECTED")


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

    @property
    def is_placeholder(self) -> bool:
        """True while we have only seen this device's slug, never its MAC."""
        return self.mac.startswith("slug:")


class EspNowHub:
    """Central state for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, base_topic: str) -> None:
        self.hass = hass
        self.entry = entry
        self.base = base_topic.rstrip("/")
        self.devices: dict[str, EspNowDevice] = {}
        self.bridge_online = False
        self.bridge_info: dict[str, Any] = {}
        #: Unique ids already handed to a platform. Shared by every platform so
        #: that an entity removed because its capability disappeared can be
        #: created again if the capability comes back.
        self.discovered: set[str] = set()
        self._unsubs: list[Callable[[], None]] = []

    async def async_start(self) -> None:
        for suffix, handler in (
            (TOPIC_BRIDGE_STATE, self._on_bridge_state),
            (TOPIC_BRIDGE_INFO, self._on_bridge_info),
            (TOPIC_BRIDGE_DEVICES, self._on_devices),
            ("+/state", self._on_device_state),
            ("+/availability", self._on_availability),
            (f"+/{TOPIC_SUFFIX_COMMAND_RESULT}", self._on_command_result),
        ):
            self._unsubs.append(
                await mqtt.async_subscribe(
                    self.hass, f"{self.base}/{suffix}", handler, 0
                )
            )
        _LOGGER.info("ESP-NOW hub listening on %s/#", self.base)

    async def async_stop(self) -> None:
        while self._unsubs:
            unsub = self._unsubs.pop()
            unsub()

    # ------------------------------------------------------------------
    # Bridge-level topics
    # ------------------------------------------------------------------

    @staticmethod
    def _text(payload: Any) -> str:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="ignore")
        return str(payload)

    @classmethod
    def _json(cls, payload: Any) -> Any:
        try:
            return json.loads(cls._text(payload))
        except json.JSONDecodeError:
            return None

    @callback
    def _on_bridge_state(self, msg: mqtt.ReceiveMessage) -> None:
        self.bridge_online = self._text(msg.payload).strip().lower() == "online"
        async_dispatcher_send(self.hass, SIGNAL_BRIDGE_UPDATED, self.entry.entry_id)
        # Device entities derive `available` from the bridge too, so they have to
        # be told as well; otherwise they keep showing a stale value until their
        # own state topic happens to fire.
        for mac in list(self.devices):
            async_dispatcher_send(
                self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, mac
            )

    @callback
    def _on_bridge_info(self, msg: mqtt.ReceiveMessage) -> None:
        info = self._json(msg.payload)
        if not isinstance(info, dict):
            return
        self.bridge_info = info
        async_dispatcher_send(self.hass, SIGNAL_BRIDGE_UPDATED, self.entry.entry_id)

    @callback
    def _on_devices(self, msg: mqtt.ReceiveMessage) -> None:
        lst = self._json(msg.payload)
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
            dev.hop = _as_int(item.get("hop"), dev.hop)
            dev.rssi = _as_int(item.get("rssi"), dev.rssi)
            self.devices[mac] = dev
            self._absorb_placeholder(dev)
            async_dispatcher_send(
                self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, mac
            )

    def _absorb_placeholder(self, dev: EspNowDevice) -> None:
        """Fold a slug-keyed placeholder into the real device that owns the slug.

        A retained `<slug>/state` can arrive before `bridge/devices`, and it
        carries no MAC, so `_on_device_state` has to park it under a synthetic
        `slug:<slug>` key. Once the device list tells us the real MAC we move
        that state across and drop the placeholder, otherwise its entities live
        on forever as a duplicate set with unusable unique ids.
        """
        key = f"slug:{dev.slug}"
        placeholder = self.devices.get(key)
        if placeholder is None or placeholder is dev:
            return
        merged = dict(placeholder.state)
        merged.update(dev.state)
        dev.state = merged
        for cap in placeholder.caps:
            if cap not in dev.caps:
                dev.caps.append(cap)
        if dev.hop is None:
            dev.hop = placeholder.hop
        if dev.rssi is None:
            dev.rssi = placeholder.rssi
        if not dev.via:
            dev.via = placeholder.via
        if not dev.node_role:
            dev.node_role = placeholder.node_role
        del self.devices[key]
        _LOGGER.debug("merged placeholder %s into %s", key, dev.mac)
        async_dispatcher_send(
            self.hass, SIGNAL_DEVICE_REMOVED, self.entry.entry_id, key
        )

    @callback
    def _on_availability(self, msg: mqtt.ReceiveMessage) -> None:
        # espnow2mqtt/<slug>/availability
        parts = msg.topic.split("/")
        if len(parts) < 3:
            return
        slug = parts[-2]
        online = self._text(msg.payload).strip().lower() == "online"
        dev = self._find_by_slug(slug)
        if dev is None:
            return
        dev.online = online
        async_dispatcher_send(
            self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, dev.mac
        )

    @callback
    def _on_command_result(self, msg: mqtt.ReceiveMessage) -> None:
        """Surface the outcome of a command the bridge forwarded to a device.

        `<slug>/set` is fire-and-forget, so without this the only trace of a
        failed command was a warning in the bridge's own log. The bridge now
        republishes the coordinator's ack, and we turn failures into an event on
        the HA bus that automations can react to.
        """
        parts = msg.topic.split("/")
        if len(parts) < 3:
            return
        slug = parts[-2]
        result = self._json(msg.payload)
        if not isinstance(result, dict):
            return
        if result.get("ok"):
            _LOGGER.debug("command %s to %s succeeded", result.get("id"), slug)
            return
        dev = self._find_by_slug(slug)
        error = str(result.get("error") or "unknown")
        _LOGGER.warning(
            "command %s to %s failed: %s", result.get("id"), slug, error
        )
        self.hass.bus.async_fire(
            EVENT_COMMAND_FAILED,
            {
                "entry_id": self.entry.entry_id,
                "slug": slug,
                "mac": dev.mac if dev and not dev.is_placeholder else None,
                "name": dev.name if dev else "",
                "id": result.get("id"),
                "error": error,
                "payload": result.get("payload"),
            },
        )

    # ------------------------------------------------------------------
    # Device state
    # ------------------------------------------------------------------

    def _find_by_slug(self, slug: str) -> EspNowDevice | None:
        for dev in self.devices.values():
            if dev.slug == slug:
                return dev
        return None

    @callback
    def _on_device_state(self, msg: mqtt.ReceiveMessage) -> None:
        parts = msg.topic.split("/")
        if len(parts) < 3 or parts[-1] != "state":
            return
        slug = parts[-2]
        if slug == "bridge":
            return
        payload = self._json(msg.payload)
        if not isinstance(payload, dict):
            return

        dev = self._find_by_slug(slug)
        if dev is None:
            # Park it under the slug until `bridge/devices` reveals the MAC,
            # then `_absorb_placeholder` folds it into the real device.
            dev = EspNowDevice(mac=f"slug:{slug}", name=slug)
            self.devices[dev.mac] = dev
        if not dev.name:
            dev.name = slug

        self._apply_caps(dev, payload)
        if payload.get("node_role"):
            dev.node_role = str(payload["node_role"])
        dev.hop = _as_int(payload.get("hop"), dev.hop)
        dev.via = str(payload.get("via") or dev.via)

        merged = dict(dev.state)
        merged.update(payload)
        dev.state = _normalize_state(merged)
        dev.online = True
        async_dispatcher_send(
            self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, dev.mac
        )

    @staticmethod
    def _apply_caps(dev: EspNowDevice, payload: dict[str, Any]) -> None:
        """Refresh `dev.caps` from the state payload.

        The bridge sends `caps` explicitly whenever the 160-byte report budget
        allows it. When it does, it is authoritative and *replaces* what we had,
        so a capability can genuinely disappear. Only when `caps` is absent do
        we fall back to inferring from the payload keys, which can only add.
        """
        caps = payload.get("caps")
        if isinstance(caps, list):
            dev.caps = [str(c).lower() for c in caps]
        elif isinstance(caps, str) and caps:
            dev.caps = [c.strip().lower() for c in caps.split(",") if c.strip()]
        else:
            for key, cap in _CAP_FROM_STATE_KEY.items():
                if key in payload and cap not in dev.caps:
                    dev.caps.append(cap)

        # A dimmable or tunable bulb is a light, not a switch, even if the only
        # boolean it reports is `switch`. Do this after the block above so it
        # also corrects an explicit caps list that just says `switch`.
        if any(k in payload for k in ("brightness", "level", "color_temp")):
            if "light" not in dev.caps:
                dev.caps.append("light")
        if "light" in dev.caps and "switch" in dev.caps:
            dev.caps = [c for c in dev.caps if c != "switch"]

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def async_permit_join(self, seconds: int = 60) -> None:
        seconds = max(1, min(300, int(seconds)))
        await mqtt.async_publish(
            self.hass, f"{self.base}/{TOPIC_PERMIT_JOIN}", str(seconds), 0, False
        )

    async def async_publish_set(self, device: EspNowDevice, payload: dict) -> None:
        await mqtt.async_publish(
            self.hass,
            f"{self.base}/{device.slug}/set",
            json.dumps(payload),
            0,
            False,
        )

    async def async_set_switch(self, device: EspNowDevice, value: str) -> None:
        await self.async_publish_set(device, {"switch": value})


def _as_int(raw: Any, fallback: int | None) -> int | None:
    if raw is None:
        return fallback
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def _normalize_state(merged: dict[str, Any]) -> dict[str, Any]:
    """Coerce the value spellings a device may use into the ones entities read."""
    if "switch" in merged:
        merged["switch"] = (
            "ON" if str(merged["switch"]).upper() in ("ON", "1", "TRUE") else "OFF"
        )
    for key in _BINARY_KEYS:
        if key in merged:
            merged[key] = (
                "ON" if str(merged[key]).upper() in _BINARY_TRUE else "OFF"
            )
    if "lock" in merged:
        locked = str(merged["lock"]).upper() in ("LOCKED", "LOCK", "1", "TRUE")
        merged["lock"] = "LOCKED" if locked else "UNLOCKED"
    if "cover" in merged:
        cover = str(merged["cover"]).upper()
        if cover in ("CLOSED", "CLOSE"):
            merged["cover"] = "CLOSED"
        elif cover in ("OPEN", "OPENING"):
            merged["cover"] = "OPEN"
        else:
            merged["cover"] = cover
    return merged
