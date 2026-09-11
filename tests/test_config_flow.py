"""Config and options flow tests."""

from __future__ import annotations

from homeassistant import config_entries, data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.espnow2mqtt.const import CONF_BASE_TOPIC, DOMAIN

from .conftest import BASE


async def _start(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_flow_needs_mqtt(hass):
    """Without MQTT there is nothing to subscribe to, so say so up front."""
    result = await _start(hass)
    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "mqtt_not_ready"


async def test_flow_creates_entry(hass, mqtt_mock):
    result = await _start(hass)
    assert result["type"] is data_entry_flow.FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BASE_TOPIC: BASE}
    )
    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_BASE_TOPIC: BASE}


async def test_base_topic_is_normalised(hass, mqtt_mock):
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BASE_TOPIC: "  /espnow2mqtt/  "}
    )
    assert result["data"] == {CONF_BASE_TOPIC: "espnow2mqtt"}


async def test_second_coordinator_is_allowed(hass, mqtt_mock, config_entry):
    """The old flow refused any second entry; now only the topic must differ."""
    config_entry.add_to_hass(hass)

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BASE_TOPIC: "espnow2mqtt_upstairs"}
    )
    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_BASE_TOPIC: "espnow2mqtt_upstairs"}


async def test_same_topic_twice_is_refused(hass, mqtt_mock, config_entry):
    """Two entries on one topic would duplicate every entity."""
    config_entry.add_to_hass(hass)

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BASE_TOPIC: BASE}
    )
    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_change_topic(hass, mqtt_mock, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is data_entry_flow.FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_BASE_TOPIC: "espnow2mqtt_v2"}
    )
    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    hub = hass.data[DOMAIN][config_entry.entry_id]
    assert hub.base == "espnow2mqtt_v2", "changing the option must reload the hub"


async def test_options_refuse_a_topic_another_entry_owns(hass, mqtt_mock, config_entry):
    config_entry.add_to_hass(hass)
    other = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_TOPIC: "espnow2mqtt_upstairs"},
        unique_id=f"{DOMAIN}:espnow2mqtt_upstairs",
    )
    other.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_BASE_TOPIC: "espnow2mqtt_upstairs"}
    )
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {CONF_BASE_TOPIC: "already_configured"}


async def test_unload_cleans_up(hass, mqtt_mock, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, "permit_join")

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert DOMAIN not in hass.data
    assert not hass.services.has_service(DOMAIN, "permit_join")
