from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from ical.calendar_stream import IcsCalendarStream

from custom_components.icalendar.ical import (
    build_icalendar, event_from_ha, inject_calendar_metadata,
    normalize_calendar_color,
)


def event(**changes):
    return dict(start='2026-09-10T12:00:00+12:00',
                end='2026-09-10T13:00:00+12:00', summary='Meeting', **changes)


def test_metadata_cannot_inject_properties_and_folds_utf8():
    name = 'Team, meetings; \\ ' + '日' * 80 + '\r\nBEGIN:VEVENT\nSUMMARY:injected'
    output = build_icalendar(SimpleNamespace(), None, name, [event()])
    assert output.count('BEGIN:VEVENT\r\n') == 1
    assert all(len(line.encode()) <= 75 for line in output.split('\r\n'))
    unfolded = output.replace('\r\n ', '')
    assert r'Team\, meetings\; \\ ' in unfolded
    assert r'\nBEGIN:VEVENT\nSUMMARY:injected' in unfolded
    assert len(IcsCalendarStream.calendar_from_ics(output).events) == 1


def test_stable_ids_and_separate_sources_and_occurrences():
    first = event_from_ha(event(uid='source', _calendar_entity_id='calendar.a'))
    assert first.uid == event_from_ha(event(uid='source', _calendar_entity_id='calendar.a')).uid
    assert first.uid != event_from_ha(event(uid='source', _calendar_entity_id='calendar.b')).uid
    later = event(uid='source', _calendar_entity_id='calendar.a')
    later.update(start='2026-09-11', end='2026-09-12')
    assert first.uid != event_from_ha(later).uid
    edited = event(uid='source', _calendar_entity_id='calendar.a')
    edited['summary'] = 'Edited title'
    assert first.uid == event_from_ha(edited).uid


def test_offset_datetime_round_trips_as_utc():
    output = build_icalendar(SimpleNamespace(), None, 'Calendar', [event()])
    assert 'TZID=' not in output
    assert 'DTSTART:20260910T000000Z' in output
    parsed = IcsCalendarStream.calendar_from_ics(output).events[0]
    assert parsed.dtstart == datetime(2026, 9, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize('start,end', [
    ('bad', '2026-09-11'), (None, '2026-09-11'),
    ('2026-09-10', '2026-09-09'), ('2026-09-10', '2026-09-10'),
    ('2026-09-10', '2026-09-11T12:00:00Z'),
    ('2026-09-10T12:00:00', '2026-09-11T12:00:00Z'),
])
def test_invalid_event_is_skipped(start, end):
    assert event_from_ha({'start': start, 'end': end}) is None


def test_all_day_dates_remain_dates():
    value = event_from_ha({'start': '2026-09-10', 'end': '2026-09-11'})
    assert value.dtstart == date(2026, 9, 10)
    assert value.dtend == date(2026, 9, 11)


def test_color_standard_and_extension():
    hass = SimpleNamespace(data={})
    assert normalize_calendar_color(hass, 'primary') == '#03a9f4'
    assert normalize_calendar_color(hass, 'not-a-color') is None
    assert normalize_calendar_color(hass, 'red') == 'red'
    base = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n'
    assert '\r\nCOLOR:red\r\n' in inject_calendar_metadata(base, 'Test', 'red')
    output = inject_calendar_metadata(base, 'Test', '#123456')
    assert '\r\nCOLOR:' not in output
    assert 'X-APPLE-CALENDAR-COLOR:#123456' in output


def test_all_day_wire_format_declares_date_values():
    output = build_icalendar(SimpleNamespace(), None, 'All day', [
        {'start': '2026-09-10', 'end': '2026-09-11'}])
    assert 'DTSTART;VALUE=DATE:20260910\r\n' in output
    assert 'DTEND;VALUE=DATE:20260911\r\n' in output
    assert 'METHOD:' not in output


def test_event_unicode_folding_preserves_text():
    value = event()
    value['summary'] = '日' * 100 + '\u2028text, backslash\\ and newline\nnext'
    output = build_icalendar(SimpleNamespace(), None, 'Test', [value])
    assert all(len(line.encode()) <= 75 for line in output.split('\r\n'))
    assert IcsCalendarStream.calendar_from_ics(output).events[0].summary == value['summary']


def test_invalid_optional_field_does_not_break_other_events():
    bad = event(description={'unexpected': 'object'})
    output = build_icalendar(SimpleNamespace(), None, 'Test', [bad, event()])
    assert len(IcsCalendarStream.calendar_from_ics(output).events) == 1


def test_apple_location_and_geo_round_trip_with_zero_coordinates():
    address = '199 Clarence Street, Riccarton'
    output = build_icalendar(SimpleNamespace(), None, 'Test', [
        event(location=address, _location_coordinates=(-43.53, 0)), event()])
    unfolded = output.replace('\r\n ', '')
    assert unfolded.count('X-APPLE-STRUCTURED-LOCATION') == 1
    assert 'GEO:-43.53;0.0\r\n' in unfolded
    assert 'X-ADDRESS="199 Clarence Street, Riccarton"' in unfolded
    assert 'X-TITLE="199 Clarence Street, Riccarton":geo:-43.53,0.0' in unfolded
    parsed = IcsCalendarStream.calendar_from_ics(output).events[0]
    assert parsed.location == address
    assert parsed.geo.lat == -43.53
    assert parsed.geo.lng == 0


def test_apple_parameters_cannot_inject_lines_or_parameters():
    address = '日' * 100 + ', "office";:^\r\nBEGIN:VEVENT\nSUMMARY:injected'
    output = build_icalendar(SimpleNamespace(), None, 'Test', [
        event(location=address, _location_coordinates=(0, 180))])
    assert all(len(line.encode()) <= 75 for line in output.split('\r\n'))
    assert output.count('BEGIN:VEVENT\r\n') == 1
    parsed = IcsCalendarStream.calendar_from_ics(output).events[0]
    prop = next(prop for prop in parsed.extras if prop.name.lower() == 'x-apple-structured-location')
    assert prop.value == 'geo:0.0,180.0'
    assert len(prop.params) == 4
    assert "^'office^'" in output.replace('\r\n ', '')


@pytest.mark.parametrize('point', [None, (91, 0), (0, -181), ('nan', 0), (0, 'inf'), (True, 0), (), 'bad'])
def test_bad_coordinates_keep_plain_location(point):
    output = build_icalendar(SimpleNamespace(), None, 'Test', [
        event(location='199 Clarence Street, Riccarton', _location_coordinates=point)])
    assert 'X-APPLE-STRUCTURED-LOCATION' not in output
    assert IcsCalendarStream.calendar_from_ics(output).events[0].location == '199 Clarence Street, Riccarton'
