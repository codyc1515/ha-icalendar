"""Data models for iCalendar integration runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any

from .const import (CONF_CALENDAR_ENTITY_ID, CONF_CALENDAR_ENTITY_IDS,
                    CONF_SELECTION_MODE, MODE_INCLUDE)


def calendar_selection(data: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Read selection, including legacy single-calendar entries."""
    entities = data.get(CONF_CALENDAR_ENTITY_IDS)
    if entities is None:
        entity = data.get(CONF_CALENDAR_ENTITY_ID)
        entities = [entity] if entity else []
    return data.get(CONF_SELECTION_MODE, MODE_INCLUDE), list(dict.fromkeys(entities))


@dataclass(slots=True)
class ICalendarRuntimeData:
    """Runtime data for one config entry."""

    calendar_entity_ids: list[str]
    selection_mode: str
    secret: str
    geocoding_url: str = ""

    cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    store: Any = None
