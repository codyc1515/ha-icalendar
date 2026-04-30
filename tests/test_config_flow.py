"""Regression coverage for changing calendar selections from settings."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.icalendar.config_flow import ICalendarOptionsFlow
from homeassistant.helpers import selector


@pytest.fixture
def settings(monkeypatch):
    for name in ('SelectSelector', 'SelectSelectorConfig', 'EntitySelector', 'EntitySelectorConfig'):
        monkeypatch.setattr(selector, name, Mock(return_value=lambda value: value), raising=False)
    entry = SimpleNamespace(entry_id='feed', data={
        'calendar_entity_id': 'calendar.original', 'secret': 'a' * 24, 'geocoding_url': '',
    })
    flow = ICalendarOptionsFlow()
    flow.config_entry = entry
    flow.hass = SimpleNamespace(
        config=SimpleNamespace(internal_url='https://ha.local', external_url=None),
        states=SimpleNamespace(get=lambda entity: object() if entity != 'calendar.missing' else None),
        config_entries=SimpleNamespace(
            async_entries=Mock(return_value=[entry]),
            async_update_entry=Mock(), async_reload=AsyncMock(),
        ),
    )
    flow.async_show_form = Mock(side_effect=lambda **kwargs: kwargs)
    flow.async_create_entry = Mock(return_value={'type': 'create_entry'})
    return flow


def defaults(result):
    return {key.schema: key.default() for key in result['data_schema'].schema}


def test_settings_shows_legacy_selection_and_url(settings):
    result = asyncio.run(settings.async_step_init())
    assert defaults(result) == {
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'secret': 'a' * 24, 'geocoding_url': '',
    }
    assert 'https://ha.local/api/ics/feed/' in result['description_placeholders']['url_block']


@pytest.mark.parametrize('mode,entities,secret', [
    ('include', ['calendar.changed'], ''),
    ('exclude', [], 'b' * 24),
])
def test_settings_saves_selection_and_reloads(settings, mode, entities, secret):
    result = asyncio.run(settings.async_step_init({
        'selection_mode': mode, 'calendar_entity_ids': entities, 'secret': secret,
    }))
    assert result['type'] == 'create_entry'
    saved = settings.hass.config_entries.async_update_entry.call_args.kwargs
    assert saved['data'] == {
        'selection_mode': mode, 'calendar_entity_ids': entities,
        'secret': secret or 'a' * 24, 'geocoding_url': '',
    }
    assert mode in saved['title']
    settings.hass.config_entries.async_reload.assert_awaited_once_with('feed')


@pytest.mark.parametrize('mode,entities,secret,error', [
    ('include', [], '', 'no_calendars'),
    ('include', ['calendar.missing'], '', 'entity_not_found'),
    ('invalid', [], '', 'invalid_selection_mode'),
    ('exclude', [], 'short', 'invalid_secret'),
])
def test_invalid_settings_preserve_input_without_saving(settings, mode, entities, secret, error):
    data = {'selection_mode': mode, 'calendar_entity_ids': entities, 'secret': secret}
    result = asyncio.run(settings.async_step_init(data))
    assert error in result['errors'].values()
    assert defaults(result) == {**data, 'geocoding_url': ''}
    settings.hass.config_entries.async_update_entry.assert_not_called()
    settings.hass.config_entries.async_reload.assert_not_awaited()


def test_duplicate_selection_is_rejected(settings):
    settings.hass.config_entries.async_entries.return_value.append(SimpleNamespace(
        entry_id='other', data={'selection_mode': 'exclude', 'calendar_entity_ids': []},
    ))
    result = asyncio.run(settings.async_step_init({
        'selection_mode': 'exclude', 'calendar_entity_ids': [],
    }))
    assert result['errors'] == {'base': 'already_configured'}
    settings.hass.config_entries.async_update_entry.assert_not_called()


def test_settings_saves_geocoding_endpoint(settings):
    result = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'geocoding_url': 'https://geo.example/search',
    }))
    assert result['type'] == 'create_entry'
    assert settings.hass.config_entries.async_update_entry.call_args.kwargs['data']['geocoding_url'] == 'https://geo.example/search'


@pytest.mark.parametrize('url', ['ftp://geo/search', 'https://', 'https://user:pass@geo/search',
                                'https://geo/search?q=test', 'https://geo/search#fragment'])
def test_invalid_geocoding_endpoint(settings, url):
    result = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'geocoding_url': url,
    }))
    assert result['errors'] == {'geocoding_url': 'invalid_geocoding_url'}
    settings.hass.config_entries.async_update_entry.assert_not_called()
