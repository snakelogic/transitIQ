"""Delhi OTD GTFS-Realtime adapter with short process-local caching."""

from __future__ import annotations

import os
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi
from transit.cache import read_snapshot, write_snapshot

OTD_VEHICLE_URL = "https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb"
VEHICLE_CACHE_SECONDS = int(os.environ.get("OTD_CACHE_SECONDS", "15"))
STALE_MAX_AGE_SECONDS = int(os.environ.get("OTD_STALE_MAX_AGE_SECONDS", "600"))
MAX_FEED_BYTES = 25 * 1024 * 1024
_cache_lock = threading.Lock()
_cached_feed: dict | None = None
_cache_expires_at = 0.0
_refreshing = False
_retry_after = 0.0


def _key_required() -> dict:
    return {
        "data": [], "live": False, "status": "key_required", "count": 0,
        "message": "Request an official Delhi OTD realtime API key and set OTD_API_KEY.",
        "source": "Delhi Open Transit Data",
        "source_url": "https://otd.delhi.gov.in/data/realtime/",
    }


def _fetch_vehicle_positions(api_key: str) -> dict:
    from google.transit import gtfs_realtime_pb2
    from google.protobuf.message import DecodeError

    url = f"{OTD_VEHICLE_URL}?{urlencode({'key': api_key})}"
    request = Request(url, headers={"User-Agent": "SmartBusTracking/0.3 (+local transit dashboard)"})
    try:
        with urlopen(request, timeout=15, context=ssl.create_default_context(cafile=certifi.where())) as response:
            raw_feed = response.read(MAX_FEED_BYTES + 1)
            if len(raw_feed) > MAX_FEED_BYTES:
                raise ValueError("GTFS-Realtime response exceeded the configured size limit.")
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(raw_feed)
    except HTTPError as error:
        # Do not include the upstream URL in the response: it contains the private API key.
        return {
            "data": [], "live": False, "status": "upstream_error", "count": 0,
            "upstream_status": error.code,
            "message": "Delhi OTD rejected or could not serve the realtime request.",
            "source": "Delhi Open Transit Data",
            "source_url": "https://otd.delhi.gov.in/data/realtime/",
        }
    except (URLError, TimeoutError, ValueError, DecodeError):
        return {
            "data": [], "live": False, "status": "upstream_error", "count": 0,
            "message": "Delhi OTD realtime data is temporarily unavailable or invalid.",
            "source": "Delhi Open Transit Data",
            "source_url": "https://otd.delhi.gov.in/data/realtime/",
        }

    position_type = gtfs_realtime_pb2.VehiclePosition
    vehicles = []
    for entity in feed.entity:
        if not entity.HasField("vehicle") or not entity.vehicle.HasField("position"):
            continue
        vehicle = entity.vehicle
        position = vehicle.position
        vehicles.append({
            "id": vehicle.vehicle.id or entity.id,
            "label": vehicle.vehicle.label or vehicle.vehicle.id or entity.id,
            "route_id": vehicle.trip.route_id or None,
            "trip_id": vehicle.trip.trip_id or None,
            "stop_id": vehicle.stop_id if vehicle.HasField("stop_id") else None,
            "stop_sequence": vehicle.current_stop_sequence if vehicle.HasField("current_stop_sequence") else None,
            "current_status": position_type.VehicleStopStatus.Name(vehicle.current_status) if vehicle.HasField("current_status") else None,
            "occupancy_status": position_type.OccupancyStatus.Name(vehicle.occupancy_status) if vehicle.HasField("occupancy_status") else None,
            "occupancy_percentage": vehicle.occupancy_percentage if vehicle.HasField("occupancy_percentage") else None,
            "lat": position.latitude,
            "lon": position.longitude,
            "bearing": position.bearing if position.HasField("bearing") else None,
            "speed_mps": position.speed if position.HasField("speed") else None,
            "timestamp": vehicle.timestamp if vehicle.HasField("timestamp") else None,
        })
    return {
        "data": vehicles,
        "live": True,
        "status": "connected",
        "count": len(vehicles),
        "feed_timestamp": feed.header.timestamp if feed.header.HasField("timestamp") else None,
        "fetched_at": int(time.time()),
        "source": "Delhi Open Transit Data",
        "source_url": "https://otd.delhi.gov.in/data/realtime/",
    }


def get_vehicle_positions(force_refresh: bool = False) -> dict:
    """Return live positions or a clearly marked recent SQLite snapshot."""
    global _cached_feed, _cache_expires_at, _refreshing, _retry_after
    api_key = os.environ.get("OTD_API_KEY")
    if not api_key:
        return _key_required()

    now = time.time()
    snapshot = read_snapshot("delhi-otd-vehicles")
    with _cache_lock:
        payload = _cached_feed if _cached_feed is not None else (snapshot[0] if snapshot else None)
        saved_at = float(payload.get("fetched_at", now)) if payload else 0
        if not force_refresh and payload is not None and now - saved_at < VEHICLE_CACHE_SECONDS:
            _cache_expires_at = now + max(0, VEHICLE_CACHE_SECONDS - (now - saved_at))
            result = dict(payload)
            result["cache_age_seconds"] = max(0, int(now - saved_at))
            return result
        if not force_refresh and payload is not None and now - saved_at <= STALE_MAX_AGE_SECONDS:
            if not _refreshing and now >= _retry_after:
                _refreshing = True
                threading.Thread(target=_refresh_feed, args=(api_key,), daemon=True).start()
            return _stale_copy(payload, saved_at, now)
        if _refreshing:
            if payload is not None:
                return _stale_copy(payload, saved_at, now)
        _refreshing = True
    result = _fetch_and_store(api_key)
    if result["live"]:
        return result
    if payload is not None and now - saved_at <= STALE_MAX_AGE_SECONDS:
        return _stale_copy(payload, saved_at, now)
    return result


def _stale_copy(payload: dict, saved_at: float, now: float) -> dict:
    result = dict(payload)
    result.update(
        live=False, status="stale", stale=True,
        count=len(result.get("data", [])),
        cache_age_seconds=max(0, int(now - saved_at)),
        message="Showing the last successful Delhi OTD positions; the live feed is unavailable or refreshing.",
    )
    return result


def _refresh_feed(api_key: str) -> None:
    _fetch_and_store(api_key)


def _fetch_and_store(api_key: str) -> dict:
    global _cached_feed, _cache_expires_at, _refreshing, _retry_after
    try:
        result = _fetch_vehicle_positions(api_key)
        if result["live"] and result["data"]:
            _cached_feed = result
            _cache_expires_at = time.time() + VEHICLE_CACHE_SECONDS
            write_snapshot("delhi-otd-vehicles", result, result["fetched_at"])
            _retry_after = 0
        elif result["live"]:
            result = dict(result, live=False, status="empty_feed", message="Delhi OTD returned no positioned vehicles.")
            _retry_after = time.time() + 15
        else:
            _retry_after = time.time() + 15
        return result
    finally:
        with _cache_lock:
            _refreshing = False
