"""Config flow for Fuzzy Assist."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_FALLBACK_AGENT,
    CONF_STEP,
    CONF_THRESHOLD,
    DEFAULT_FALLBACK_AGENT,
    DEFAULT_STEP,
    DEFAULT_THRESHOLD,
    DOMAIN,
)


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_THRESHOLD,
                default=defaults.get(CONF_THRESHOLD, DEFAULT_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=50, max=100, step=1, mode=selector.NumberSelectorMode.SLIDER
                )
            ),
            vol.Required(
                CONF_STEP, default=defaults.get(CONF_STEP, DEFAULT_STEP)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5, max=50, step=5, mode=selector.NumberSelectorMode.SLIDER
                )
            ),
            vol.Required(
                CONF_FALLBACK_AGENT,
                default=defaults.get(CONF_FALLBACK_AGENT, DEFAULT_FALLBACK_AGENT),
            ): selector.ConversationAgentSelector(),
        }
    )


class FuzzyAssistConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single form with the tuning options."""
        if user_input is not None:
            return self.async_create_entry(title="Fuzzy Assist", data={}, options=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options flow to retune later."""
        return FuzzyAssistOptionsFlow()


class FuzzyAssistOptionsFlow(OptionsFlow):
    """Change threshold / step / fallback agent."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=_schema(dict(self.config_entry.options))
        )
