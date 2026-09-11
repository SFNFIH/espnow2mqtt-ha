"""Test fixtures for the ESP-NOW 2 MQTT integration.

Runs against a real Home Assistant core via
pytest-homeassistant-custom-component, so the tests exercise the actual entity
platforms, dispatcher and registries rather than stand-ins.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.espnow2mqtt.const import (  # noqa: E402
    CONF_BASE_TOPIC,
    DOMAIN,
)

BASE = "espnow2mqtt"
MAC = "11:22:33:44:55:66"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let HA load `custom_components/` during tests."""
    return


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """Tolerate the MQTT integration's own periodic timer.

    `mqtt_mock` leaves `MQTT._async_start_misc_periodic` scheduled, which has
    nothing to do with this integration.
    """
    return True


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_TOPIC: BASE},
        unique_id=f"{DOMAIN}:{BASE}",
        title="ESP-NOW 2 MQTT",
    )


@pytest.fixture
async def hub(hass, mqtt_mock, config_entry):
    """A loaded config entry, returning its hub."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][config_entry.entry_id]


async def publish(hass, topic: str, payload: Any) -> None:
    """Feed a message in as if the bridge had published it."""
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    async_fire_mqtt_message(hass, topic, payload)
    await hass.async_block_till_done()


async def bring_up_bridge(hass, *, info: dict | None = None) -> None:
    await publish(hass, f"{BASE}/bridge/state", "online")
    if info is not None:
        await publish(hass, f"{BASE}/bridge/info", info)


async def announce_device(
    hass, *, mac: str = MAC, name: str = "node1", model: str = "c3-env", **extra
) -> None:
    await publish(
        hass,
        f"{BASE}/bridge/devices",
        [{"mac": mac, "name": name, "model": model, "online": True, **extra}],
    )


async def report_state(hass, slug: str, payload: dict) -> None:
    await publish(hass, f"{BASE}/{slug}/state", payload)
