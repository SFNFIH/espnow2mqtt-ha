"""Regression tests for the implementation gaps listed in docs/README.md.

Each test names the gap it pins down. They are written against a real Home
Assistant instance, so a fix that only looks right in isolation but does not
actually reach the state machine will fail here.
"""

from __future__ import annotations

import pytest
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.espnow2mqtt.const import DOMAIN, EVENT_COMMAND_FAILED

from .conftest import (
    BASE,
    MAC,
    announce_device,
    bring_up_bridge,
    publish,
    report_state,
)

COORDINATOR_INFO = {
    "type": "hello",
    "version": 2,
    "role": "coordinator",
    "mac": "AA:BB:CC:DD:EE:FF",
    "fw": "0.4.0-idf",
    "channel": 1,
    "mesh": True,
    "stack": "esp-idf",
}


# ---------------------------------------------------------------------------
# Gap: bridge/info was never subscribed, so bridge_info stayed empty forever
# ---------------------------------------------------------------------------


async def test_bridge_info_is_captured(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)

    assert hub.bridge_info["fw"] == "0.4.0-idf"
    assert hub.bridge_info["channel"] == 1


async def test_coordinator_exposes_firmware_and_channel(hass, hub, config_entry):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)

    state = hass.states.get("binary_sensor.esp_now_coordinator_bridge")
    assert state is not None
    assert state.state == "on"
    assert state.attributes["fw"] == "0.4.0-idf"
    assert state.attributes["channel"] == 1
    assert state.attributes["mac"] == "AA:BB:CC:DD:EE:FF"

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "bridge")})
    assert device is not None
    assert device.sw_version == "0.4.0-idf"


# ---------------------------------------------------------------------------
# Gap: three entries in the caps map were unreachable, so devices that only
# reported fan_mode / target_temperature / current_temperature were never seen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "cap", "entity_id"),
    [
        ({"fan_mode": "low"}, "fan", "fan.node1_fan"),
        ({"target_temperature": 21.0}, "climate", "climate.node1_thermostat"),
        ({"current_temperature": 19.5}, "climate", "climate.node1_thermostat"),
    ],
)
async def test_value_only_payloads_infer_their_platform(
    hass, hub, payload, cap, entity_id
):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(hass, "node1", payload)

    assert cap in hub.devices[MAC].caps
    assert hass.states.get(entity_id) is not None


async def test_thermostat_reports_its_setpoint(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(
        hass,
        "node1",
        {"hvac_mode": "heat", "target_temperature": 21.5, "current_temperature": 19.0},
    )

    state = hass.states.get("climate.node1_thermostat")
    assert state.state == "heat"
    assert state.attributes["temperature"] == 21.5
    assert state.attributes["current_temperature"] == 19.0


# ---------------------------------------------------------------------------
# Gap: a retained state arriving before bridge/devices created a slug: device
# that never merged with the real one, leaving a duplicate set of entities
# ---------------------------------------------------------------------------


async def test_placeholder_is_absorbed_by_the_real_device(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)

    # State first, with no device list to give us the MAC.
    await report_state(hass, "node1", {"temperature": 22.5, "caps": ["temperature"]})
    assert "slug:node1" in hub.devices

    await announce_device(hass)

    assert "slug:node1" not in hub.devices, "the placeholder should be gone"
    assert MAC in hub.devices
    # The state it had collected must survive the merge, not be thrown away.
    assert hub.devices[MAC].state["temperature"] == 22.5
    assert hub.devices[MAC].caps == ["temperature"]


async def test_placeholder_leaves_no_duplicate_entities(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await report_state(hass, "node1", {"temperature": 22.5, "caps": ["temperature"]})
    await announce_device(hass)

    registry = er.async_get(hass)
    temps = [
        entry
        for entry in registry.entities.values()
        if entry.domain == "sensor" and entry.unique_id.endswith("_temperature")
    ]
    assert len(temps) == 1
    assert temps[0].unique_id == f"{MAC}_temperature"

    devices = dr.async_get(hass)
    assert devices.async_get_device(identifiers={(DOMAIN, "slug:node1")}) is None
    assert devices.async_get_device(identifiers={(DOMAIN, MAC)}) is not None


# ---------------------------------------------------------------------------
# Gap: entities only ever grew, so a promoted light kept its stale Switch and
# a capability that disappeared left an entity frozen at its last value
# ---------------------------------------------------------------------------


async def test_switch_is_removed_when_the_device_turns_out_to_be_a_light(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)

    # First report looks like a plain relay.
    await report_state(hass, "node1", {"switch": "ON", "caps": ["switch"]})
    assert hass.states.get("switch.node1_switch") is not None

    # The next one proves it dims.
    await report_state(hass, "node1", {"switch": "ON", "brightness": 200})

    assert hass.states.get("light.node1_light") is not None
    assert hass.states.get("switch.node1_switch") is None
    assert er.async_get(hass).async_get("switch.node1_switch") is None


async def test_entity_goes_away_when_its_capability_does(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(hass, "node1", {"contact": "OPEN", "caps": ["contact"]})
    assert hass.states.get("binary_sensor.node1_contact") is not None

    # Reflashed with different firmware: it is a thermometer now.
    await report_state(hass, "node1", {"temperature": 20.0, "caps": ["temperature"]})

    assert hass.states.get("binary_sensor.node1_contact") is None
    assert hass.states.get("sensor.node1_temperature") is not None


async def test_capability_coming_back_recreates_the_entity(hass, hub):
    """Removal must clear the bookkeeping, or the entity can never return."""
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(hass, "node1", {"contact": "ON", "caps": ["contact"]})
    await report_state(hass, "node1", {"temperature": 20.0, "caps": ["temperature"]})
    assert hass.states.get("binary_sensor.node1_contact") is None

    await report_state(hass, "node1", {"contact": "ON", "caps": ["contact"]})
    assert hass.states.get("binary_sensor.node1_contact") is not None


async def test_empty_caps_never_deletes_anything(hass, hub):
    """An empty caps list means 'not known yet', not 'supports nothing'."""
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(hass, "node1", {"switch": "ON", "caps": ["switch"]})
    assert hass.states.get("switch.node1_switch") is not None

    await report_state(hass, "node1", {"caps": []})
    assert hass.states.get("switch.node1_switch") is not None


# ---------------------------------------------------------------------------
# Gap: only the Bridge entity listened for the bridge going offline, so device
# entities kept a stale availability
# ---------------------------------------------------------------------------


async def test_devices_go_unavailable_when_the_bridge_drops(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(hass, "node1", {"switch": "ON", "caps": ["switch"]})
    assert hass.states.get("switch.node1_switch").state == "on"

    await publish(hass, f"{BASE}/bridge/state", "offline")

    assert hass.states.get("switch.node1_switch").state == "unavailable"
    assert hass.states.get("binary_sensor.esp_now_coordinator_bridge").state == "off"

    await publish(hass, f"{BASE}/bridge/state", "online")
    assert hass.states.get("switch.node1_switch").state == "on"


async def test_device_availability_topic_is_honoured(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(hass, "node1", {"switch": "ON", "caps": ["switch"]})

    await publish(hass, f"{BASE}/node1/availability", "offline")
    assert hass.states.get("switch.node1_switch").state == "unavailable"


# ---------------------------------------------------------------------------
# Gap: a light's colour mode was frozen in __init__
# ---------------------------------------------------------------------------


async def test_light_gains_colour_temp_after_creation(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)

    # Created from a report that happens not to carry color_temp.
    await report_state(hass, "node1", {"switch": "ON", "brightness": 254, "caps": ["light"]})
    state = hass.states.get("light.node1_light")
    assert state.attributes["supported_color_modes"] == ["brightness"]

    # A later report proves it is tunable white.
    await report_state(hass, "node1", {"color_temp": 370})

    state = hass.states.get("light.node1_light")
    assert state.attributes["supported_color_modes"] == ["color_temp"]
    assert state.attributes["color_mode"] == "color_temp"
    assert state.attributes["color_temp_kelvin"] == pytest.approx(2703, abs=2)


async def test_light_brightness_scales_both_ways(hass, hub, mqtt_mock):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(hass, "node1", {"switch": "ON", "brightness": 254, "caps": ["light"]})

    assert hass.states.get("light.node1_light").attributes["brightness"] == 255

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": "light.node1_light", "brightness": 255},
        blocking=True,
    )
    payload = _last_publish(mqtt_mock, f"{BASE}/node1/set")
    assert payload == {"switch": "ON", "brightness": 254}


# ---------------------------------------------------------------------------
# Gap: the sensor precision field was unpacked and discarded
# ---------------------------------------------------------------------------


async def test_sensor_precision_reaches_the_registry(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(
        hass, "node1", {"temperature": 22.4567, "caps": ["temperature"]}
    )

    entry = er.async_get(hass).async_get("sensor.node1_temperature")
    assert entry is not None
    assert entry.options["sensor"]["suggested_display_precision"] == 1


# ---------------------------------------------------------------------------
# Gap: a button capability produced no entity at all
# ---------------------------------------------------------------------------


async def test_button_capability_produces_an_event_entity(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(hass, "node1", {"caps": ["button"]})

    state = hass.states.get("event.node1_button")
    assert state is not None
    assert state.attributes["event_types"] == [
        "press",
        "double_press",
        "long_press",
        "release",
    ]


async def test_button_fires_on_a_new_value(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(hass, "node1", {"caps": ["button"]})

    await report_state(hass, "node1", {"button": 1, "button_action": "double_press"})
    state = hass.states.get("event.node1_button")
    assert state.attributes["event_type"] == "double_press"
    first = state.state

    # An unrelated field changing must not replay the press.
    await report_state(hass, "node1", {"rssi": -60})
    assert hass.states.get("event.node1_button").state == first

    await report_state(hass, "node1", {"button": 2, "button_action": "hold"})
    assert hass.states.get("event.node1_button").attributes["event_type"] == "long_press"


# ---------------------------------------------------------------------------
# Gap: the mesh-topology constants were unused, so hop/via were unreachable
# ---------------------------------------------------------------------------


async def test_mesh_topology_is_exposed_as_attributes(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(
        hass,
        "node1",
        {
            "switch": "ON",
            "caps": ["switch"],
            "hop": 2,
            "via": "AA:BB:CC:00:11:22",
            "node_role": "leaf",
        },
    )

    attrs = hass.states.get("switch.node1_switch").attributes
    assert attrs["mac"] == MAC
    assert attrs["caps"] == ["switch"]
    assert attrs["hop"] == 2
    assert attrs["via"] == "AA:BB:CC:00:11:22"
    assert attrs["node_role"] == "leaf"


# ---------------------------------------------------------------------------
# Gap: a failed command was invisible outside the bridge's own log
# ---------------------------------------------------------------------------


async def test_failed_command_fires_an_event(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(hass, "node1", {"switch": "OFF", "caps": ["switch"]})

    events = []
    hass.bus.async_listen(EVENT_COMMAND_FAILED, events.append)

    await publish(
        hass,
        f"{BASE}/node1/command_result",
        {"id": 7, "ok": False, "error": "timeout", "payload": {"switch": "ON"}},
    )

    assert len(events) == 1
    data = events[0].data
    assert data["error"] == "timeout"
    assert data["slug"] == "node1"
    assert data["mac"] == MAC
    assert data["payload"] == {"switch": "ON"}


async def test_successful_command_fires_nothing(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(hass, "node1", {"switch": "OFF", "caps": ["switch"]})

    events = []
    hass.bus.async_listen(EVENT_COMMAND_FAILED, events.append)

    await publish(hass, f"{BASE}/node1/command_result", {"id": 8, "ok": True})

    assert events == []


# ---------------------------------------------------------------------------
# Gap: unique_id was the domain, so only one coordinator could ever be added
# ---------------------------------------------------------------------------


async def test_a_second_coordinator_can_be_added(hass, mqtt_mock, config_entry):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.espnow2mqtt.const import CONF_BASE_TOPIC

    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)

    second = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_TOPIC: "espnow2mqtt_upstairs"},
        unique_id=f"{DOMAIN}:espnow2mqtt_upstairs",
        title="ESP-NOW 2 MQTT (upstairs)",
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    hubs = hass.data[DOMAIN]
    assert len(hubs) == 2
    assert {h.base for h in hubs.values()} == {BASE, "espnow2mqtt_upstairs"}

    # The two must stay independent: a device on one topic is not on the other.
    await publish(hass, "espnow2mqtt_upstairs/bridge/state", "online")
    await publish(
        hass,
        "espnow2mqtt_upstairs/bridge/devices",
        [{"mac": "AA:00:00:00:00:01", "name": "attic", "online": True}],
    )
    downstairs = hass.data[DOMAIN][config_entry.entry_id]
    upstairs = hass.data[DOMAIN][second.entry_id]
    assert "AA:00:00:00:00:01" in upstairs.devices
    assert "AA:00:00:00:00:01" not in downstairs.devices


# ---------------------------------------------------------------------------
# Other corrections shipped alongside the gap fixes
# ---------------------------------------------------------------------------


async def test_unknown_hvac_mode_is_unknown_not_off(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(hass, "node1", {"hvac_mode": "dry", "caps": ["climate"]})

    # Reporting "off" for a running thermostat would be an active lie.
    assert hass.states.get("climate.node1_thermostat").state == "unknown"


async def test_cover_position_is_inverted_for_ha(hass, hub, mqtt_mock):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    # Firmware: 0 = fully open, 100 = fully closed.
    await report_state(hass, "node1", {"position": 30, "cover": "OPEN", "caps": ["cover"]})

    state = hass.states.get("cover.node1_cover")
    assert state.attributes["current_position"] == 70
    assert state.state == "open"

    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {"entity_id": "cover.node1_cover", "position": 70},
        blocking=True,
    )
    assert _last_publish(mqtt_mock, f"{BASE}/node1/set") == {"position": 30}


async def test_cover_closed_follows_the_device_verdict(hass, hub):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    # The firmware calls anything at or past 95 closed; we must not
    # second-guess it with a threshold of our own.
    await report_state(hass, "node1", {"position": 97, "cover": "CLOSED", "caps": ["cover"]})

    state = hass.states.get("cover.node1_cover")
    assert state.state == "closed"
    assert state.attributes["current_position"] == 3


async def test_commands_are_never_retained(hass, hub, mqtt_mock):
    await bring_up_bridge(hass, info=COORDINATOR_INFO)
    await announce_device(hass)
    await report_state(hass, "node1", {"switch": "OFF", "caps": ["switch"]})

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.node1_switch"}, blocking=True
    )

    for call in mqtt_mock.async_publish.mock_calls:
        topic = call.args[0]
        if topic.endswith("/set"):
            # A retained command would re-fire on every HA restart.
            assert call.args[3] is False


def _last_publish(mqtt_mock, topic: str):
    """The payload of the most recent publish to `topic`, decoded."""
    import json

    for call in reversed(mqtt_mock.async_publish.mock_calls):
        if call.args and call.args[0] == topic:
            return json.loads(call.args[1])
    raise AssertionError(f"nothing was published to {topic}")
