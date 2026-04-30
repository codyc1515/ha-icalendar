"""iCalendar formatting and color resolution."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
import hashlib
import json
import re
from typing import Any

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event
from ical.exceptions import CalendarParseError
from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.types.geo import Geo
from homeassistant.components import frontend
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .location import coordinates


def build_icalendar(
    hass: HomeAssistant,
    entity_id: str | None,
    calendar_name: str,
    events: list[dict[str, Any]],
) -> str:
    """Build iCalendar feed output using HA's shared ical library."""
    calendar = Calendar()
    calendar.prodid = "-//Home Assistant//iCal Subscription 2.0//EN"
    calendar.version = "2.0"
    calendar.calscale = "GREGORIAN"

    for ha_event in events:
        if event := event_from_ha(ha_event):
            calendar.events.append(event)

    output = IcsCalendarStream.calendar_to_ics(calendar)
    return inject_calendar_metadata(
        output,
        calendar_name=calendar_name,
        calendar_color=resolve_calendar_color(hass, entity_id) if entity_id else None,
    )


def escape_text(value: str) -> str:
    """Escape an RFC 5545 TEXT value before adding content lines."""
    return (value.replace("\\", "\\\\").replace("\r\n", "\n")
            .replace("\r", "\n").replace("\n", "\\n")
            .replace(";", "\\;").replace(",", "\\,"))


def fold_line(line: str) -> str:
    """Fold at 75 UTF-8 octets without splitting a code point."""
    lines = []
    part = ""
    size = 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > 75:
            lines.append(part)
            part, size = " ", 1
        part += char
        size += width
    lines.append(part)
    return "\r\n".join(lines)


def inject_calendar_metadata(ics: str, calendar_name: str, calendar_color: str | None) -> str:
    """Inject NAME/X-WR-CALNAME/COLOR in VCALENDAR headers."""
    # The pinned serializer folds by characters and omits DATE parameters.
    # Unfold before applying the wire-format constraints ourselves.
    unfolded = re.sub(r"\n[ \t]", "", ics.replace("\r\n", "\n"))
    lines = unfolded.split("\n")
    injected: list[str] = []
    inserted = False
    for line in lines:
        if not line:
            continue
        line = re.sub(r"^(DTSTART|DTEND):([0-9]{8})$",
                      r"\1;VALUE=DATE:\2", line)
        injected.append(fold_line(line))
        if not inserted and line == "VERSION:2.0":
            injected.append(fold_line(f"NAME:{escape_text(calendar_name)}"))
            injected.append(fold_line(f"X-WR-CALNAME:{escape_text(calendar_name)}"))
            if calendar_color and is_css_color_name(calendar_color):
                injected.append(f"COLOR:{calendar_color}")
            elif calendar_color and is_hex_color(calendar_color):
                injected.append(f"X-APPLE-CALENDAR-COLOR:{calendar_color}")
            inserted = True
    return "\r\n".join(injected) + "\r\n"


def event_from_ha(event: dict[str, Any]) -> Event | None:
    """Convert Home Assistant event payload to an ical.Event."""
    try:
        start = parse_ha_datetime_or_date(event["start"])
        end = parse_ha_datetime_or_date(event["end"])
        if type(start) is not type(end) or end <= start:
            return None
        # HA returns expanded occurrences, not recurrence rules. Include the
        # occurrence start so repeated instances with the same source UID differ.
        identity = [event.get("_calendar_entity_id", ""),
                    str(event.get("uid") or event.get("summary") or ""),
                    start.isoformat()]
        uid = hashlib.sha256(json.dumps(identity).encode("utf-8")).hexdigest()
        result = Event(
            uid=f"{uid}@ha-icalendar",
            summary=str(event.get("summary") or ""),
            start=start,
            end=end,
            description=event.get("description"),
            location=event.get("location"),
        )
        if result.location and (point := coordinates(event.get("_location_coordinates"))):
            result.geo = Geo(*point)
            # RFC 6868 parameter encoding differs from RFC 5545 TEXT escaping.
            title = result.location.replace("^", "^^").replace('"', "^'")
            title = title.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "^n")
            result.extras.append(ParsedProperty(
                name="X-APPLE-STRUCTURED-LOCATION",
                value=f"geo:{point[0]},{point[1]}",
                params=[
                    ParsedPropertyParameter(name="VALUE", values=["URI"]),
                    ParsedPropertyParameter(name="X-ADDRESS", values=[title]),
                    ParsedPropertyParameter(name="X-APPLE-RADIUS", values=["100"]),
                    ParsedPropertyParameter(name="X-TITLE", values=[title]),
                ],
            ))
        return result
    except (KeyError, ValueError, TypeError, CalendarParseError):
        return None


def parse_ha_datetime_or_date(value: str) -> datetime | date:
    """Parse HA event date/datetime string."""
    if "T" in value:
        parsed = datetime.fromisoformat(value)
        # Numeric offsets otherwise become undefined TZIDs in the ICS library.
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed
    return datetime.strptime(value, "%Y-%m-%d").date()


def resolve_calendar_color(hass: HomeAssistant, entity_id: str) -> str | None:
    """Resolve calendar color from HA entity options."""
    resolved: str | None = None
    registry = er.async_get(hass)
    if registry_entry := registry.async_get(entity_id):
        if color := registry_entry.options.get("calendar", {}).get("color"):
            resolved = str(color)
    return normalize_calendar_color(hass, resolved)


def normalize_calendar_color(hass: HomeAssistant, color: str | None) -> str | None:
    """Normalize calendar color token into a concrete ICS-friendly color."""
    if not color:
        return None

    value = color.strip()
    if not value:
        return None

    if is_hex_color(value) or is_css_color_name(value):
        return value

    lowered = value.lower()
    theme_vars = active_theme_vars(hass)
    semantic_map = {
        "primary": "primary-color",
        "accent": "accent-color",
    }
    if (theme_key := semantic_map.get(lowered)) and (theme_value := theme_vars.get(theme_key)):
        theme_color = str(theme_value).strip()
        if is_hex_color(theme_color) or is_css_color_name(theme_color):
            return theme_color

    if lowered == "primary":
        return frontend.DEFAULT_THEME_COLOR

    return None


def active_theme_vars(hass: HomeAssistant) -> Mapping[str, Any]:
    """Return active frontend theme variables if available."""
    themes = hass.data.get(frontend.DATA_THEMES, {})
    if not isinstance(themes, dict):
        return {}

    active_theme = hass.data.get(frontend.DATA_DEFAULT_THEME, frontend.DEFAULT_THEME)
    if not active_theme or active_theme == frontend.DEFAULT_THEME:
        return {}

    variables = themes.get(active_theme, {})
    if isinstance(variables, dict):
        return variables
    return {}


def is_hex_color(value: str) -> bool:
    """Check whether value is a #RGB or #RRGGBB hex color."""
    return bool(re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", value))


def is_css_color_name(value: str) -> bool:
    """Check the named colors allowed by RFC 7986."""
    return value.lower() in CSS3_COLOR_NAMES


# CSS Color Module Level 3, section 4.3 (RFC 7986 COLOR values).
CSS3_COLOR_NAMES = frozenset(
    'aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue '
    'blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk '
    'crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki '
    'darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen '
    'darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue '
    'dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro '
    'ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo '
    'ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan '
    'lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen '
    'lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen '
    'linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple '
    'mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred '
    'midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab '
    'orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip '
    'peachpuff peru pink plum powderblue purple red rosybrown royalblue saddlebrown salmon '
    'sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow '
    'springgreen steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke '
    'yellow yellowgreen '
    .split()
)
