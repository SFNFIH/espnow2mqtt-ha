"""Config flow for ESP-NOW 2 MQTT."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import TextSelector

from .const import CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC, DOMAIN


class EspNow2MqttConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if mqtt.DOMAIN not in self.hass.config.components:
            return self.async_abort(reason="mqtt_not_ready")

        errors: dict[str, str] = {}
        if user_input is not None:
            base = (user_input.get(CONF_BASE_TOPIC) or DEFAULT_BASE_TOPIC).strip().rstrip("/")
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="ESP-NOW 2 MQTT",
                data={CONF_BASE_TOPIC: base},
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_TOPIC, default=DEFAULT_BASE_TOPIC): TextSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return EspNow2MqttOptionsFlow(config_entry)


class EspNow2MqttOptionsFlow(config_entries.OptionsFlow):
    """Options flow."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            base = (user_input.get(CONF_BASE_TOPIC) or DEFAULT_BASE_TOPIC).strip().rstrip("/")
            return self.async_create_entry(title="", data={CONF_BASE_TOPIC: base})

        current = self._entry.options.get(
            CONF_BASE_TOPIC,
            self._entry.data.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC),
        )
        schema = vol.Schema(
            {vol.Required(CONF_BASE_TOPIC, default=current): TextSelector()}
        )
        return self.async_show_form(step_id="init", data_schema=schema)
