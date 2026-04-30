import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from custom_components.icalendar import async_unload_entry
from custom_components.icalendar.config_flow import _is_secret_valid, _build_feed_urls
from custom_components.icalendar.http import ICalendarView
from custom_components.icalendar.models import ICalendarRuntimeData


def fixture():
    entry = SimpleNamespace(domain='icalendar', runtime_data=ICalendarRuntimeData([], 'include', 'a' * 24))
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=lambda _: entry))
    return hass, entry, ICalendarView(hass)


def test_unicode_auth_is_rejected_without_exception():
    _, _, view = fixture()
    assert asyncio.run(view.get(None, 'entry', '日' * 24)).status == 401


def test_unload_revokes_feed():
    hass, entry, view = fixture()
    asyncio.run(async_unload_entry(hass, entry))
    assert asyncio.run(view.get(None, 'entry', 'a' * 24)).status == 503


def test_empty_feed_and_private_cache_policy():
    _, _, view = fixture()
    response = asyncio.run(view.get(None, 'entry', 'a' * 24))
    assert response.status == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.content_type == 'text/calendar'


def test_secret_and_url_validation():
    assert _is_secret_valid('aB_-' * 6)
    for secret in ('short', '日' * 20, 'a' * 20 + '/', 'a' * 20 + '?', 'a' * 20 + '\n'):
        assert not _is_secret_valid(secret)
    hass = SimpleNamespace(config=SimpleNamespace(internal_url='https://ha.local/', external_url=None))
    assert _build_feed_urls(hass, 'entry', 'legacy?#')[0] == 'https://ha.local/api/ics/entry/legacy%3F%23'


def test_combined_feed_namespaces_identical_events():
    from ical.calendar_stream import IcsCalendarStream

    hass, entry, view = fixture()
    entry.runtime_data.calendar_entity_ids = ['calendar.a', 'calendar.b']
    hass.states = SimpleNamespace(get=lambda _: SimpleNamespace(name='Calendar'))
    view._fetch_events = AsyncMock(return_value=[{
        'start': '2026-09-10', 'end': '2026-09-11', 'summary': 'Same event',
    }])
    response = asyncio.run(view.get(None, 'entry', 'a' * 24))
    parsed = IcsCalendarStream.calendar_from_ics(response.text)
    assert len({event.uid for event in parsed.events}) == 2


def test_exclusion_is_applied_before_fetching():
    hass, entry, view = fixture()
    entry.runtime_data.selection_mode = 'exclude'
    entry.runtime_data.calendar_entity_ids = ['calendar.private']
    hass.states = SimpleNamespace(
        get=lambda _: SimpleNamespace(name='Calendar'),
        async_entity_ids=lambda _: ['calendar.private', 'calendar.a', 'calendar.b'],
    )
    view._fetch_events = AsyncMock(return_value=[])
    assert asyncio.run(view.get(None, 'entry', 'a' * 24)).status == 200
    assert [call.args[0] for call in view._fetch_events.call_args_list] == ['calendar.a', 'calendar.b']


def test_wrong_secret_does_not_access_calendar_data():
    hass, _, view = fixture()
    hass.states = Mock()
    view._fetch_events = AsyncMock()
    assert asyncio.run(view.get(None, 'entry', 'wrong')).status == 401
    hass.states.get.assert_not_called()
    view._fetch_events.assert_not_called()


def test_missing_source_uses_cache_while_other_source_refreshes():
    hass, entry, view = fixture()
    runtime = entry.runtime_data
    runtime.calendar_entity_ids = ['calendar.a', 'calendar.b']
    runtime.cache['calendar.a'] = {'name': 'A', 'events': [
        {'start': '2026-09-10', 'end': '2026-09-11', 'summary': 'Cached'}]}
    runtime.store = Mock()
    hass.states = SimpleNamespace(get=lambda entity: None if entity == 'calendar.a' else SimpleNamespace(name='B'))
    view._fetch_events = AsyncMock(return_value=[])
    response = asyncio.run(view.get(None, 'entry', 'a' * 24))
    assert response.status == 200
    assert 'Cached' in response.text
    view._fetch_events.assert_awaited_once_with('calendar.b')
    assert runtime.cache['calendar.b']['events'] == []
    assert runtime.store.async_delay_save.call_args.args[0]() == runtime.cache


def test_uncached_failure_does_not_prevent_healthy_source_caching():
    from homeassistant.exceptions import HomeAssistantError
    hass, entry, view = fixture()
    entry.runtime_data.calendar_entity_ids = ['calendar.a', 'calendar.b']
    hass.states = SimpleNamespace(get=lambda _: SimpleNamespace(name='Calendar'))
    view._fetch_events = AsyncMock(side_effect=[HomeAssistantError(), []])
    assert asyncio.run(view.get(None, 'entry', 'a' * 24)).status == 503
    assert entry.runtime_data.cache['calendar.b']['events'] == []


def test_sources_fetch_concurrently_and_timeout_uses_cache(monkeypatch):
    import custom_components.icalendar.http as http
    monkeypatch.setattr(http, 'FETCH_TIMEOUT', 0.05)
    hass, entry, view = fixture()
    runtime = entry.runtime_data
    runtime.calendar_entity_ids = ['calendar.a', 'calendar.b']
    runtime.cache['calendar.a'] = {'name': 'A', 'events': []}
    hass.states = SimpleNamespace(get=lambda _: SimpleNamespace(name='Calendar'))

    async def run():
        started = asyncio.Event()
        async def fetch(entity):
            if entity == 'calendar.a':
                await started.wait()
                await asyncio.Future()
            started.set()
            return []
        view._fetch_events = fetch
        response = await view.get(None, 'entry', 'a' * 24)
        assert started.is_set()
        assert response.status == 200
        assert 'calendar.b' in runtime.cache
    asyncio.run(run())


def test_setup_restores_without_accessing_calendars(monkeypatch):
    import custom_components.icalendar as integration
    hass, entry, view = fixture()
    entry.entry_id = 'entry'
    entry.data = {'calendar_entity_ids': ['calendar.a'], 'secret': 'a' * 24}
    cached = {'calendar.a': {'name': 'A', 'events': []}}
    store = Mock(async_load=AsyncMock(return_value=cached))
    monkeypatch.setattr(integration, 'Store', Mock(return_value=store))
    hass.states = Mock()
    assert asyncio.run(integration.async_setup_entry(hass, entry))
    hass.states.get.assert_not_called()
    assert entry.runtime_data.cache == cached
    assert entry.runtime_data.store is store


def test_exclude_mode_restores_missing_cached_sources():
    hass, entry, view = fixture()
    entry.runtime_data.selection_mode = 'exclude'
    entry.runtime_data.cache = {
        'calendar.a': {'name': 'A', 'events': []},
        'calendar.b': {'name': 'B', 'events': []},
    }
    hass.states = SimpleNamespace(get=lambda _: None, async_entity_ids=lambda _: [])
    response = asyncio.run(view.get(None, 'entry', 'a' * 24))
    assert response.status == 200


def test_unavailable_source_recovers_and_empty_result_replaces_cache():
    hass, entry, view = fixture()
    runtime = entry.runtime_data
    runtime.cache['calendar.a'] = {'name': 'Old', 'events': [{'summary': 'Old'}]}
    state = SimpleNamespace(name='New', state='unavailable')
    hass.states = SimpleNamespace(get=lambda _: state)
    view._fetch_events = AsyncMock(return_value=[])
    assert asyncio.run(view._calendar_data('calendar.a', runtime))['name'] == 'Old'
    view._fetch_events.assert_not_awaited()
    state.state = 'off'
    assert asyncio.run(view._calendar_data('calendar.a', runtime)) == {'name': 'New', 'events': []}


def test_remove_entry_deletes_persistent_cache(monkeypatch):
    import custom_components.icalendar as integration
    hass, entry, _ = fixture()
    entry.entry_id = 'entry'
    store = Mock(async_remove=AsyncMock())
    factory = Mock(return_value=store)
    monkeypatch.setattr(integration, 'Store', factory)
    asyncio.run(integration.async_remove_entry(hass, entry))
    factory.assert_called_once_with(hass, 1, 'icalendar.entry.events')
    store.async_remove.assert_awaited_once()


def test_address_lookup_reaches_feed_without_changing_cached_events():
    from ical.calendar_stream import IcsCalendarStream
    hass, entry, _ = fixture()
    entry.runtime_data.calendar_entity_ids = ['calendar.a', 'calendar.b']
    entry.runtime_data.geocoding_url = 'https://geo.example/search'
    hass.states = SimpleNamespace(get=lambda _: SimpleNamespace(name='Calendar'))
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=(-43.53, 172.6)))
    view = ICalendarView(hass, resolver)
    original = {'start': '2026-09-10', 'end': '2026-09-11',
                'summary': 'Meeting', 'location': '199 Clarence Street, Riccarton'}
    view._fetch_events = AsyncMock(return_value=[original])
    output = asyncio.run(view.get(None, 'entry', 'a' * 24))
    parsed = IcsCalendarStream.calendar_from_ics(output.text)
    assert len(parsed.events) == 2
    assert all(event.geo.lat == -43.53 for event in parsed.events)
    assert '_location_coordinates' not in original
    assert all('_location_coordinates' not in source['events'][0]
               for source in entry.runtime_data.cache.values())
    resolver.resolve.assert_awaited_with('https://geo.example/search', original['location'])


def test_disabled_geocoding_does_not_call_resolver():
    hass, _, _ = fixture()
    resolver = SimpleNamespace(resolve=AsyncMock())
    assert asyncio.run(ICalendarView(hass, resolver).get(None, 'entry', 'a' * 24)).status == 200
    resolver.resolve.assert_not_awaited()
