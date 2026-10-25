"""API endpoints for Delhi OpenStreetMap and Delhi OTD data."""

from flask import Blueprint, current_app, jsonify, request

from transit.osm import TransitSourceError, get_transit_data
from transit.search import search_destinations
from transit.vehicles import get_vehicle_positions

api = Blueprint("api", __name__)


@api.get("/transit")
def transit_data():
    try:
        return jsonify(data=get_transit_data())
    except TransitSourceError as error:
        return jsonify(error={"code": "transit_source_unavailable", "message": str(error)}), 503


@api.get("/directions")
def directions():
    origin = request.args.get("from", "").strip()
    destination = request.args.get("to", "").strip()
    if not origin or not destination:
        return jsonify(error={"code": "locations_required", "message": "Enter both a starting point and a destination."}), 400
    if len(origin) > 120 or len(destination) > 120:
        return jsonify(error={"code": "location_too_long", "message": "Keep each location under 120 characters."}), 400
    try:
        transit = get_transit_data()
    except TransitSourceError as error:
        return jsonify(error={"code": "transit_source_unavailable", "message": str(error)}), 503

    result = search_destinations(origin, destination, transit)
    if result["status"] == "routes_found":
        try:
            vehicles = get_vehicle_positions()
        except Exception:
            # Live positions are optional; a missing OTD dependency/feed must not hide mapped routes.
            current_app.logger.exception("Could not read optional live positions for destination search")
            vehicles = {"status": "unavailable", "live": False, "data": [], "message": "Live vehicle positions are temporarily unavailable."}
        result = search_destinations(origin, destination, transit, vehicles)
    return jsonify(result)


@api.get("/vehicles")
def vehicles():
    result = get_vehicle_positions()
    if result.get("data") and request.args.get("all") != "1":
        query = request.args.get("q", "").strip().casefold()
        route_id = request.args.get("route_id", "").strip().casefold()
        status = request.args.get("status", "").strip().upper()
        page = max(1, request.args.get("page", default=1, type=int) or 1)
        page_size = min(100, max(1, request.args.get("page_size", default=50, type=int) or 50))
        filtered = result["data"]
        if query:
            filtered = [bus for bus in filtered if query in " ".join(str(bus.get(key) or "") for key in ("id", "label", "route_id", "trip_id", "stop_id")).casefold()]
        if route_id:
            filtered = [bus for bus in filtered if str(bus.get("route_id") or "").casefold() == route_id]
        if status:
            filtered = [bus for bus in filtered if str(bus.get("current_status") or "UNKNOWN").upper() == status]
        filtered.sort(key=lambda bus: (str(bus.get("route_id") or ""), str(bus.get("label") or bus.get("id") or "")))
        total = len(filtered)
        start = (page - 1) * page_size
        result = dict(result)
        result.update(
            data=filtered[start:start + page_size],
            total=total,
            page=page,
            page_size=page_size,
            pages=(total + page_size - 1) // page_size,
        )
    return jsonify(result), (200 if result["live"] or result.get("status") in {"key_required", "stale", "empty_feed"} else 503)


@api.get("/vehicles/<path:vehicle_id>")
def vehicle_detail(vehicle_id: str):
    result = get_vehicle_positions()
    if not result.get("data") and not result["live"]:
        return jsonify(error={"code": result["status"], "message": result["message"]}), 503
    vehicle = next((item for item in result["data"] if str(item["id"]) == vehicle_id), None)
    if vehicle is None:
        return jsonify(error={"code": "not_found", "message": "Vehicle is not present in the latest OTD feed."}), 404
    return jsonify(data=vehicle, feed_timestamp=result.get("feed_timestamp"), source=result["source"], stale=result.get("stale", False), cache_age_seconds=result.get("cache_age_seconds")), (200 if result["live"] or result.get("stale") else 503)
