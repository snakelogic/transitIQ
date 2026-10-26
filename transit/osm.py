"""Live, cached transit features from OpenStreetMap's Overpass API."""

from __future__ import annotations

import json
import os
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi
from transit.cache import read_snapshot, write_snapshot


DELHI_BBOX = (28.40, 76.84, 28.88, 77.36)  # south, west, north, east
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ALTERNATE_OVERPASS_URL = "https://overpass.private.coffee/api/interpreter"
THIRD_OVERPASS_URL = "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
OVERPASS_URL = os.environ.get("OVERPASS_URL", DEFAULT_OVERPASS_URL)
OVERPASS_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("OVERPASS_REQUEST_TIMEOUT_SECONDS", "12"))
CACHE_SECONDS = int(os.environ.get("OSM_CACHE_SECONDS", "900"))
STALE_MAX_AGE_SECONDS = int(os.environ.get("OSM_STALE_MAX_AGE_SECONDS", "604800"))
_cache_lock = threading.Lock()
_cache: dict[str, object] = {"expires": 0, "payload": None}
_refreshing = False
_retry_after = 0.0


class TransitSourceError(RuntimeError):
    """The upstream mapping data source could not provide current data."""


def _query(include_geometry: bool = True) -> str:
    south, west, north, east = DELHI_BBOX
    bbox = f"{south},{west},{north},{east}"
    return f"""[out:json][timeout:45];
(
  node[\"highway\"=\"bus_stop\"]({bbox});
  node[\"public_transport\"=\"platform\"][\"bus\"=\"yes\"]({bbox});
  relation[\"type\"=\"route\"][\"route\"=\"bus\"]({bbox});
);
out {"body geom" if include_geometry else "tags center"};"""


def _post_query(endpoint: str, query: str) -> dict:
    request = Request(
        endpoint,
        data=urlencode({"data": query}).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "SmartBusTracking/0.3 (+local transit dashboard)",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=OVERPASS_REQUEST_TIMEOUT_SECONDS, context=ssl.create_default_context(cafile=certifi.where())) as response:
        return json.loads(response.read())


def _request_overpass() -> dict:
    configured_fallbacks = [
        endpoint.strip()
        for endpoint in os.environ.get("OVERPASS_FALLBACK_URLS", "").split(",")
        if endpoint.strip()
    ]
    endpoints = list(dict.fromkeys([
        os.environ.get("OVERPASS_URL", OVERPASS_URL),
        *configured_fallbacks,
        DEFAULT_OVERPASS_URL,
        ALTERNATE_OVERPASS_URL,
        THIRD_OVERPASS_URL,
    ]))
    failures = []
    metadata_fallbacks = []
    for endpoint in endpoints:
        try:
            return _post_query(endpoint, _query())
        except HTTPError as error:
            failures.append(f"{endpoint}: HTTP {error.code}")
            # A malformed query or rate limit will not be fixed by sending it to another instance.
            if error.code < 500:
                break
            metadata_fallbacks.insert(0, endpoint)
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
            failures.append(f"{endpoint}: {error}")
            if "timed out" in str(error).lower():
                metadata_fallbacks.append(endpoint)

    # Bus-stop points and route endpoint tags are useful even when a provider
    # cannot build every route's full geometry for this large region.
    for endpoint in dict.fromkeys(metadata_fallbacks):
        try:
            payload = _post_query(endpoint, _query(include_geometry=False))
            payload["route_geometry_available"] = False
            return payload
        except HTTPError as error:
            failures.append(f"{endpoint} (metadata): HTTP {error.code}")
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
            failures.append(f"{endpoint} (metadata): {error}")
    raise TransitSourceError("All configured OpenStreetMap Overpass endpoints failed: " + "; ".join(failures))


def _normalise(payload: dict) -> dict:
    stops: list[dict] = []
    routes: list[dict] = []
    features: list[dict] = []
    for item in payload.get("elements", []):
        tags = item.get("tags", {})
        element_type = item.get("type")
        if element_type == "node" and (tags.get("highway") == "bus_stop" or tags.get("public_transport") == "platform"):
            stops.append({
                "id": f"node/{item['id']}",
                "name": tags.get("name") or tags.get("name:en") or "Unnamed bus stop",
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "operator": tags.get("operator"),
                "ref": tags.get("ref"),
                "wheelchair": tags.get("wheelchair"),
                "source_url": f"https://www.openstreetmap.org/node/{item['id']}",
            })
        elif element_type == "relation" and tags.get("route") == "bus":
            route = {
                "id": f"relation/{item['id']}",
                "name": tags.get("name") or tags.get("ref") or f"Bus route {item['id']}",
                "ref": tags.get("ref"),
                "operator": tags.get("operator"),
                "from": tags.get("from"),
                "to": tags.get("to"),
                "source_url": f"https://www.openstreetmap.org/relation/{item['id']}",
            }
            routes.append(route)
            for member in item.get("members", []):
                geometry = member.get("geometry")
                if member.get("type") == "way" and geometry and len(geometry) > 1:
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": [[point["lon"], point["lat"]] for point in geometry]},
                        "properties": {"route_id": route["id"], "name": route["name"], "ref": route["ref"]},
                    })
    return {
        "city": "Delhi",
        "region": "India",
        "bounds": {"south": DELHI_BBOX[0], "west": DELHI_BBOX[1], "north": DELHI_BBOX[2], "east": DELHI_BBOX[3]},
        "stops": stops,
        "routes": routes,
        "route_features": {"type": "FeatureCollection", "features": features},
        "route_geometry_available": bool(features),
        "counts": {"stops": len(stops), "routes": len(routes)},
        "source": "OpenStreetMap contributors",
        "source_url": "https://www.openstreetmap.org/",
        "license": "ODbL",
        "fetched_at": int(time.time()),
        "cached_seconds": CACHE_SECONDS,
    }


def get_transit_data(force_refresh: bool = False) -> dict:
    global _refreshing, _retry_after
    now = time.time()
    snapshot = read_snapshot("delhi-osm-transit")
    with _cache_lock:
        payload = _cache["payload"] if _cache["payload"] is not None else (snapshot[0] if snapshot else None)
        saved_at = float(payload.get("fetched_at", now)) if payload else 0
        if not force_refresh and payload is not None and now - saved_at < CACHE_SECONDS:
            _cache["payload"] = payload
            _cache["expires"] = now + max(0, CACHE_SECONDS - (now - saved_at))
            return dict(payload)  # type: ignore[arg-type]
        if not force_refresh and payload is not None and now - saved_at <= STALE_MAX_AGE_SECONDS:
            stale = dict(payload)  # type: ignore[arg-type]
            stale.update(stale=True, cache_age_seconds=max(0, int(now - saved_at)))
            if not _refreshing and now >= _retry_after:
                _refreshing = True
                threading.Thread(target=_refresh_snapshot, daemon=True).start()
            return stale
        if _refreshing:
            if payload is not None:
                stale = dict(payload)  # type: ignore[arg-type]
                stale.update(stale=True, cache_age_seconds=max(0, int(now - saved_at)))
                return stale
            raise TransitSourceError("A transit data refresh is already in progress. Retry in a few seconds.")
        if not force_refresh and payload is None and now < _retry_after:
            raise TransitSourceError("Transit data is temporarily unavailable. Retry in a few seconds.")
        _refreshing = True
    try:
        return _refresh_snapshot()
    except TransitSourceError:
        if payload is not None and now - saved_at <= STALE_MAX_AGE_SECONDS:
            stale = dict(payload)  # type: ignore[arg-type]
            stale.update(stale=True, cache_age_seconds=max(0, int(now - saved_at)))
            return stale
        raise


def _refresh_snapshot() -> dict:
    global _refreshing, _retry_after
    try:
        result = _normalise(_request_overpass())
        write_snapshot("delhi-osm-transit", result, result["fetched_at"])
        with _cache_lock:
            _cache["payload"] = result
            _cache["expires"] = time.time() + CACHE_SECONDS
            _retry_after = 0
        return result
    except TransitSourceError:
        with _cache_lock:
            _retry_after = time.time() + 30
        raise
    finally:
        with _cache_lock:
            _refreshing = False
