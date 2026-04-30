"""Address lookup boundary tests; no real network requests."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import ClientError

from custom_components.icalendar import location


@pytest.fixture
def resolver(monkeypatch):
    store = Mock(async_load=AsyncMock(return_value=None))
    monkeypatch.setattr(location, 'Store', Mock(return_value=store))
    response = Mock(raise_for_status=Mock(), json=AsyncMock(return_value=[{'lat': '-43.53', 'lon': '172.6'}]))
    session = Mock()
    session.get.return_value = AsyncMock(__aenter__=AsyncMock(return_value=response))
    monkeypatch.setattr(location, 'async_get_clientsession', Mock(return_value=session))
    clock = SimpleNamespace(now=1000.)
    monkeypatch.setattr(location.time, 'monotonic', lambda: clock.now)
    value = location.LocationResolver(object())
    return value, session, response, clock


def test_cache_persists_and_normalizes_addresses(resolver):
    value, session, _, _ = resolver
    async def run():
        point = await value.resolve('https://geo.example/search', '199 Clarence Street, Riccarton')
        assert point == (-43.53, 172.6)
        assert await value.resolve('https://geo.example/search', ' 199  CLARENCE Street, Riccarton ') == point
        value.store.async_load.return_value = value.store.async_delay_save.call_args.args[0]()
        value.cache = {}
        await value.async_load()
        assert await value.resolve('https://geo.example/search', '199 Clarence Street, Riccarton') == point
    asyncio.run(run())
    session.get.assert_called_once()
    assert session.get.call_args.kwargs['headers']['User-Agent'].startswith('ha-icalendar/')


def test_rate_limit_and_provider_separation(resolver):
    value, session, _, clock = resolver
    async def run():
        assert await value.resolve('https://one/search', 'Address')
        assert await value.resolve('https://two/search', 'Address') is None
        assert await value.resolve('https://one/search', 'Other address') is None
        clock.now += 15
        assert await value.resolve('https://two/search', 'Address')
    asyncio.run(run())
    assert session.get.call_count == 2


@pytest.mark.parametrize('result', [[], [{'lat': 0, 'lon': 0}, {'lat': 1, 'lon': 1}]])
def test_missing_and_ambiguous_results_are_cached(resolver, result):
    value, session, response, clock = resolver
    response.json.return_value = result
    async def run():
        assert await value.resolve('https://geo/search', 'Address') is None
        clock.now += 30
        assert await value.resolve('https://geo/search', 'Address') is None
    asyncio.run(run())
    session.get.assert_called_once()
    assert value.cache


@pytest.mark.parametrize('result', [{}, [None], [{'lat': 'nan', 'lon': 0}], [{'lat': 100, 'lon': 0}]])
def test_malformed_provider_response_is_not_cached(resolver, result):
    value, _, response, _ = resolver
    response.json.return_value = result
    assert asyncio.run(value.resolve('https://geo/search', 'Address')) is None
    assert not value.cache


@pytest.mark.parametrize('error', [ClientError(), TimeoutError(), ValueError()])
def test_errors_back_off_and_retry(resolver, error):
    value, session, response, clock = resolver
    response.json.side_effect = error
    async def run():
        assert await value.resolve('https://geo/search', 'Address') is None
        clock.now += 15
        assert await value.resolve('https://geo/search', 'Other') is None
        clock.now += 45
        response.json.side_effect = None
        assert await value.resolve('https://geo/search', 'Address')
    asyncio.run(run())
    assert session.get.call_count == 2


def test_concurrent_requests_do_not_queue(resolver):
    value, session, response, _ = resolver
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()
        async def json():
            started.set()
            await finish.wait()
            return [{'lat': 0, 'lon': 0}]
        response.json.side_effect = json
        first = asyncio.create_task(value.resolve('https://geo/search', 'Address'))
        await started.wait()
        assert await value.resolve('https://geo/search', 'Address') is None
        finish.set()
        assert await first == (0, 0)
    asyncio.run(run())
    session.get.assert_called_once()


@pytest.mark.parametrize('endpoint,address', [('', 'Address'), ('https://geo/search', ''),
    ('https://geo/search', None), ('https://geo/search', 'https://meet.example/private'),
    ('https://geo/search', 'a' * 513)])
def test_disabled_or_non_address_locations_do_not_request(resolver, endpoint, address):
    value, session, _, _ = resolver
    assert asyncio.run(value.resolve(endpoint, address)) is None
    session.get.assert_not_called()
