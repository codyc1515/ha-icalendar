"""Export calendar domain entity state via iCalendar using the API."""

import logging

from html import escape
from http import HTTPStatus

from aiohttp import web
import datetime

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, CONTENT_TYPE_ICAL


_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the iCalendar component."""
    for name, value in config[DOMAIN].items():
        # Find the secret from the config file
        if name == "secret":
            secret = str(value)

            # Register the iCalendar HTTP view
            hass.http.register_view(iCalendarView(hass, secret))
            return True

    return False


class iCalendarView(HomeAssistantView):
    """Define the iCalendar view."""

    name = f"{DOMAIN}"
    url = "/api/ics/{entity_id}"

    def __init__(self, hass: HomeAssistant, secret: str) -> None:
        """Initialize the iCalendar view."""
        self.hass = hass
        self.secret = secret
        self.requires_auth = False

    async def get(self, request: web.Request, entity_id: str) -> web.Response:
        """Handle an iCalendar view request."""
        # Forbid empty secrets
        if request.query.get("s") is None:
            _LOGGER.error("Request was sent for entity '%s' without secret", entity_id)
            return web.Response(status=HTTPStatus.FORBIDDEN)

        # Only return anything with the secret supplied
        if str(request.query.get("s")) != str(self.secret):
            _LOGGER.error(
                "Request was sent for entity '%s' with invalid secret", entity_id
            )
            return web.Response(status=HTTPStatus.UNAUTHORIZED)

        # Only return calendars
        if not entity_id.startswith("calendar."):
            _LOGGER.error("Entity '%s' is not a calendar", entity_id)
            return web.Response(status=HTTPStatus.FORBIDDEN)

        # Get the calendar entity state
        self._state = self.hass.states.get(entity_id)

        # Check if the calendar entity exists
        if self._state is None:
            _LOGGER.error("Entity '%s' could not be found", entity_id)
            return web.Response(status=HTTPStatus.NOT_FOUND)

        # Check if the calendar entity is available
        if self._state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            _LOGGER.error("Entity '%s' could not be found", entity_id)
            return web.Response(status=HTTPStatus.SERVICE_UNAVAILABLE)

        # Generate the variables
        entity_id = escape(entity_id)
        start = datetime.datetime.strptime(
            self._state.attributes["start_time"], "%Y-%m-%d %H:%M:%S"
        ).strftime("%Y%m%dT%H%M%S")
        end = datetime.datetime.strptime(
            self._state.attributes["end_time"], "%Y-%m-%d %H:%M:%S"
        ).strftime("%Y%m%dT%H%M%S")
        uid = f"{entity_id}-{start}"

        # Craft the iCalendar response
        response = "BEGIN:VCALENDAR\n"
        response += "VERSION:2.0\n"
        response += "PRODID:-//Home Assistant//iCal Subscription 1.0//EN\n"
        response += "CALSCALE:GREGORIAN\n"
        response += "METHOD:PUBLISH\n"
        response += f"ORGANIZER;CN=\"{escape(self._state.attributes['friendly_name'])}\":MAILTO:{entity_id}@homeassistant.local\n"

        response += "BEGIN:VEVENT\n"

        response += f"UID:{uid}\n"
        response += f"DTSTAMP:{start}\n"
        response += f"DTSTART:{start}\n"
        response += f"DTEND:{end}\n"

        # Add available optional attribuets to the iCalendar response
        if self._state.attributes:
            if (
                "message" in self._state.attributes
                and self._state.attributes["message"] is not None
            ):
                response += f"SUMMARY:{escape(self._state.attributes['message'])}\n"

            if (
                "description" in self._state.attributes
                and self._state.attributes["description"] is not None
            ):
                response += (
                    f"DESCRIPTION:{escape(self._state.attributes['description'])}\n"
                )

            if (
                "location" in self._state.attributes
                and self._state.attributes["location"] is not None
            ):
                response += f"LOCATION:{escape(self._state.attributes['location'])}\n"

        # Finish up the iCalendar response
        response += "END:VEVENT\n"
        response += "END:VCALENDAR"

        # Return the iCalendar response
        return web.Response(body=response, content_type=CONTENT_TYPE_ICAL)
