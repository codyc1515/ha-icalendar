"""Diagnostics support for iCalendar integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.components.diagnostics import async_redact_data

from .const import CONF_SECRET
from .models import calendar_selection

TO_REDACT = {CONF_SECRET}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return diagnostics for a config entry."""
    registry = er.async_get(hass)
    mode, entity_ids = calendar_selection(entry.data)
    entities = {}
    for entity_id in entity_ids:
        registry_entry = registry.async_get(entity_id)
        entities[entity_id] = {
            "entity_exists": hass.states.get(entity_id) is not None,
            "disabled_by": registry_entry.disabled_by if registry_entry else None,
            "has_calendar_color": bool(
                registry_entry and registry_entry.options.get("calendar", {}).get("color")
            ),
        }
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "selection_mode": mode,
        "entities": entities,
    }
