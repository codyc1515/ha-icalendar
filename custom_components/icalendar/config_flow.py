"""Adds config flow for iCalendar API."""

from __future__ import annotations
import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_ENTITY_ID

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class iCalendarFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for iCalendar API."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.FlowResult:
        """Handle a flow initialized by the user."""
        _errors = {}
        if user_input is not None:
            try:
                await self.async_set_unique_id(user_input[CONF_ENTITY_ID])
                self._abort_if_unique_id_configured()
            except Exception as exc:
                _LOGGER.error(exc)
                return False
            else:
                return self.async_create_entry(
                    title=user_input[CONF_ENTITY_ID],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENTITY_ID),
                }
            ),
            errors=_errors,
        )
