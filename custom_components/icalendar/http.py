"""HTTP view for iCalendar feed exposure."""

from __future__ import annotations

import asyncio
import logging
from http import HTTPStatus
import hmac
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import CONTENT_TYPE_ICAL, DOMAIN, URL_PATH_PREFIX, MODE_EXCLUDE, NAME
from .ical import build_icalendar
from .models import ICalendarRuntimeData
from .location import LocationResolver


_LOGGER = logging.getLogger(__name__)
FETCH_TIMEOUT = 15


class ICalendarView(HomeAssistantView):
    """Serve iCalendar feeds."""

    name = DOMAIN
    url = f"{URL_PATH_PREFIX}/{{entry_id}}/{{secret}}"
    requires_auth = False

    def __init__(self, hass: HomeAssistant, resolver: LocationResolver | None = None) -> None:
        self.hass = hass
        self.resolver = resolver

    async def get(self, request: web.Request, entry_id: str, secret: str) -> web.Response:
        """Handle iCalendar feed requests."""
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            return web.Response(body="404: Not Found", status=HTTPStatus.NOT_FOUND)

        runtime_data = getattr(entry, "runtime_data", None)
        if runtime_data is None or not isinstance(runtime_data, ICalendarRuntimeData):
            return web.Response(body="503: Service Unavailable", status=HTTPStatus.SERVICE_UNAVAILABLE)

        if not secret or not runtime_data.secret:
            return web.Response(body="403: Forbidden", status=HTTPStatus.FORBIDDEN)

        if not hmac.compare_digest(secret.encode("utf-8"), runtime_data.secret.encode("utf-8")):
            return web.Response(body="401: Unauthorized", status=HTTPStatus.UNAUTHORIZED)

        entity_ids = runtime_data.calendar_entity_ids
        if runtime_data.selection_mode == MODE_EXCLUDE:
            excluded = set(entity_ids)
            entity_ids = sorted(
                entity_id for entity_id in set(self.hass.states.async_entity_ids("calendar")) | set(runtime_data.cache)
                if entity_id not in excluded
            )

        if any(not entity_id.startswith("calendar.") for entity_id in entity_ids):
            return web.Response(body="403: Forbidden", status=HTTPStatus.FORBIDDEN)

        results = await asyncio.gather(*(
            self._calendar_data(entity_id, runtime_data) for entity_id in entity_ids
        ))
        if any(result is None for result in results):
            # A partial successful feed can make subscribers delete missing events.
            return web.Response(body="503: Calendar temporarily unavailable",
                                status=HTTPStatus.SERVICE_UNAVAILABLE,
                                headers={"Retry-After": "60", "Cache-Control": "no-store"})
        events = [
            {**event, "_calendar_entity_id": entity_id}
            for entity_id, result in zip(entity_ids, results)
            for event in result["events"]
        ]

        if self.resolver and runtime_data.geocoding_url:
            for event in events:
                if point := await self.resolver.resolve(runtime_data.geocoding_url, event.get("location")):
                    event["_location_coordinates"] = point

        single_calendar = len(entity_ids) == 1
        feed = build_icalendar(
            self.hass,
            entity_ids[0] if single_calendar else None,
            results[0]["name"] if single_calendar else NAME,
            events,
        )
        return web.Response(body=feed, content_type=CONTENT_TYPE_ICAL, charset="utf-8",
                            headers={"Cache-Control": "no-store"})

    async def _calendar_data(
        self, entity_id: str, runtime: ICalendarRuntimeData
    ) -> dict[str, Any] | None:
        """Refresh one source without discarding its last successful snapshot."""
        state = self.hass.states.get(entity_id)
        if state is not None and getattr(state, "state", None) not in ("unavailable", "unknown"):
            try:
                async with asyncio.timeout(FETCH_TIMEOUT):
                    events = await self._fetch_events(entity_id)
                if events is not None:
                    runtime.cache[entity_id] = {"name": state.name, "events": events}
                    if runtime.store is not None:
                        runtime.store.async_delay_save(lambda: runtime.cache, 1)
            except (HomeAssistantError, TimeoutError):
                _LOGGER.debug("Calendar %s unavailable; using cached events", entity_id)
        return runtime.cache.get(entity_id)

    async def _fetch_events(self, entity_id: str) -> list[dict[str, Any]] | None:
        """Fetch events from Home Assistant calendar service."""
        from datetime import datetime, timedelta, timezone
        from .const import DEFAULT_FUTURE_WEEKS, DEFAULT_HISTORY_WEEKS

        start = datetime.now(timezone.utc) - timedelta(weeks=DEFAULT_HISTORY_WEEKS)
        end = datetime.now(timezone.utc) + timedelta(weeks=DEFAULT_FUTURE_WEEKS)

        events_response = await self.hass.services.async_call(
            "calendar",
            "get_events",
            {
                "entity_id": entity_id,
                "start_date_time": start.isoformat(),
                "end_date_time": end.isoformat(),
            },
            blocking=True,
            return_response=True,
        )
        if not events_response or entity_id not in events_response:
            return None
        return events_response[entity_id].get("events", [])
