"""Cached, optional address lookup using a Nominatim-compatible endpoint."""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
from typing import Any

from aiohttp import ClientError, ClientTimeout
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

CONF_GEOCODING_URL = "geocoding_url"
REQUEST_INTERVAL = 15  # At most four requests/minute across all feeds.
CACHE_TTL = 90 * 86400
MISS_TTL = 7 * 86400
USER_AGENT = "ha-icalendar/2.0 (+https://github.com/codyc1515/ha-icalendar)"
MATCH_VERSION = 2


def same_location(first: tuple[float, float], second: tuple[float, float]) -> bool:
    """Allow separate address/POI records within 50 metres of each other."""
    lat1, lat2 = math.radians(first[0]), math.radians(second[0])
    dlat = lat2 - lat1
    dlon = math.radians(second[1] - first[1])
    haversine = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(min(1, haversine))) <= 50


def coordinates(value: Any) -> tuple[float, float] | None:
    """Validate coordinates, including zero and rejecting non-finite values."""
    try:
        if len(value) != 2 or any(isinstance(item, bool) for item in value):
            return None
        lat, lon = map(float, value)
        if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except (TypeError, ValueError, OverflowError):
        pass
    return None


class LocationResolver:
    """Share persistent results and a request limiter across feed entries."""

    def __init__(self, hass):
        self.hass = hass
        self.store = Store(hass, 1, "icalendar.locations")
        self.cache: dict[str, Any] = {}
        self.lock = asyncio.Lock()
        self.next_request = 0.0

    async def async_load(self):
        """Restore lookups without contacting the provider."""
        self.cache = await self.store.async_load() or {}
        # Earlier matching rejected nearby address/POI duplicates. Retry those
        # negative results after upgrading, while retaining successful lookups.
        self.cache = {
            key: item for key, item in self.cache.items()
            if item.get("coordinates") is not None or item.get("match_version") == MATCH_VERSION
        }

    async def resolve(self, endpoint: str, address: Any) -> tuple[float, float] | None:
        """Resolve at most one new address per interval; never queue feed requests."""
        if not endpoint or not isinstance(address, str) or not address.strip():
            return None
        address = " ".join(address.split())
        if len(address) > 512 or "://" in address or address.lower().startswith(("mailto:", "geo:")):
            return None
        key = hashlib.sha256(f"{endpoint}\n{address.casefold()}".encode()).hexdigest()
        cached = self.cache.get(key)
        if cached and cached["expires"] > time.time():
            return coordinates(cached["coordinates"])
        if self.lock.locked() or time.monotonic() < self.next_request:
            return None
        async with self.lock:
            self.next_request = time.monotonic() + REQUEST_INTERVAL
            try:
                async with async_get_clientsession(self.hass).get(
                    endpoint,
                    params={"q": address, "format": "jsonv2", "limit": 2},
                    headers={"User-Agent": USER_AGENT},
                    timeout=ClientTimeout(total=3),
                ) as response:
                    response.raise_for_status()
                    results = await response.json()
                if not isinstance(results, list):
                    raise ValueError("Invalid geocoding response")
                # Providers can return both an address and a POI at that address.
                # Reject geographically distinct matches, not nearby duplicates.
                point = None
                if results:
                    points = [coordinates((result["lat"], result["lon"])) for result in results]
                    if any(candidate is None for candidate in points):
                        raise ValueError("Invalid geocoding coordinates")
                    if all(same_location(points[0], candidate) for candidate in points[1:]):
                        point = points[0]
            except (ClientError, TimeoutError, ValueError, KeyError, TypeError):
                self.next_request = time.monotonic() + 60
                return None
            now = time.time()
            self.cache = {key: item for key, item in self.cache.items() if item["expires"] > now}
            self.cache[key] = {"coordinates": point, "expires": now + (CACHE_TTL if point else MISS_TTL),
                               "match_version": MATCH_VERSION}
            # Bound storage even for feeds with frequently changing addresses.
            while len(self.cache) > 2000:
                del self.cache[next(iter(self.cache))]
            self.store.async_delay_save(lambda: self.cache, 1)
            return point
