"""Config flow for ESP-NOW 2 MQTT."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import TextSelector

from .const import CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC, DOMAIN


def _clean(base: str | None) -> str:
    return (base or DEFAULT_BASE_TOPIC).strip().strip("/") or DEFAULT_BASE_TOPIC


class EspNow2MqttConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        if mqtt.DOMAIN not in self.hass.config.components:
            return self.async_abort(reason="mqtt_not_ready")

        errors: dict[str, str] = {}
        if user_input is not None:
            base = _clean(user_input.get(CONF_BASE_TOPIC))
            # One entry per base topic rather than one entry overall: a second
            # coordinator is a second USB bridge publishing under its own
            # prefix, and there is no reason HA cannot drive both.
            await self.async_set_unique_id(f"{DOMAIN}:{base}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"ESP-NOW 2 MQTT ({base})",
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
        return EspNow2MqttOptionsFlow()


class EspNow2MqttOptionsFlow(config_entries.OptionsFlow):
    """Options flow."""

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        entry = self.config_entry
        if user_input is not None:
            base = _clean(user_input.get(CONF_BASE_TOPIC))
            other_topics = {
                _clean(
                    other.options.get(
                        CONF_BASE_TOPIC, other.data.get(CONF_BASE_TOPIC)
                    )
                )
                for other in self.hass.config_entries.async_entries(DOMAIN)
                if other.entry_id != entry.entry_id
            }
            if base in other_topics:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._schema(base),
                    errors={CONF_BASE_TOPIC: "already_configured"},
                )
            return self.async_create_entry(title="", data={CONF_BASE_TOPIC: base})

        current = _clean(
            entry.options.get(CONF_BASE_TOPIC, entry.data.get(CONF_BASE_TOPIC))
        )
        return self.async_show_form(step_id="init", data_schema=self._schema(current))

    @staticmethod
    def _schema(current: str) -> vol.Schema:
        return vol.Schema(
            {vol.Required(CONF_BASE_TOPIC, default=current): TextSelector()}
        )
