"""iCalendar integration setup and entry lifecycle."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import CONF_SECRET, DOMAIN
from .http import ICalendarView
from .models import ICalendarRuntimeData, calendar_selection
from .location import CONF_GEOCODING_URL, LocationResolver


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the iCalendar component."""
    hass.data.setdefault(DOMAIN, {})
    if not hass.data[DOMAIN].get("view_registered"):
        resolver = LocationResolver(hass)
        await resolver.async_load()
        hass.http.register_view(ICalendarView(hass, resolver))
        hass.data[DOMAIN]["view_registered"] = True
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iCalendar from a config entry."""
    mode, entity_ids = calendar_selection(entry.data)
    store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.events")
    cached = await store.async_load()

    entry.runtime_data = ICalendarRuntimeData(
        calendar_entity_ids=entity_ids,
        selection_mode=mode,
        secret=entry.data[CONF_SECRET],
        geocoding_url=entry.data.get(CONF_GEOCODING_URL, ""),
        cache=cached or {},
        store=store,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an iCalendar config entry and revoke access to its feed."""
    entry.runtime_data = None
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove stored calendar data when deleting an entry."""
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.events").async_remove()
