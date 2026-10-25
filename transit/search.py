"""Destination search over the mapped stops and route metadata we actually have."""

from __future__ import annotations

import re
import unicodedata


def _normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def _location_matches(query: str, stops: list[dict], routes: list[dict]) -> list[dict]:
    normalized = _normalise(query)
    matches = []
    for stop in stops:
        name = str(stop.get("name") or "")
        ref = str(stop.get("ref") or "")
        fields = (_normalise(name), _normalise(ref))
        score = 3 if normalized in fields else 2 if len(normalized) >= 3 and any(normalized in field for field in fields if field) else 0
        if score:
            matches.append({
                "type": "stop", "id": stop.get("id"), "name": name,
                "ref": stop.get("ref"), "lat": stop.get("lat"), "lon": stop.get("lon"),
                "source_url": stop.get("source_url"), "_score": score,
            })
    for route in routes:
        for field in ("from", "to"):
            endpoint = str(route.get(field) or "")
            endpoint_normalized = _normalise(endpoint)
            score = 3 if endpoint_normalized == normalized else 2 if len(normalized) >= 3 and normalized in endpoint_normalized else 0
            if score:
                matches.append({
                    "type": "route_endpoint", "name": endpoint,
                    "route_id": route.get("id"), "route_name": route.get("name"),
                    "source_url": route.get("source_url"), "_score": score,
                })
    matches.sort(key=lambda item: (-item["_score"], item["name"].casefold()))
    # Avoid returning duplicate endpoint labels for a route's repeated tags.
    unique = []
    seen = set()
    for match in matches:
        key = (match["type"], _normalise(match["name"]), match.get("id"), match.get("route_id"))
        if key not in seen:
            seen.add(key)
            match.pop("_score", None)
            unique.append(match)
        if len(unique) == 8:
            break
    return unique


def _endpoint_matches(endpoint: str | None, query: str, matches: list[dict]) -> bool:
    if not endpoint:
        return False
    endpoint_normalized = _normalise(endpoint)
    aliases = [_normalise(query)] + [_normalise(item["name"]) for item in matches]
    aliases.extend(_normalise(item.get("ref") or "") for item in matches if item.get("ref"))
    return any(alias and (endpoint_normalized == alias or (len(alias) >= 5 and alias in endpoint_normalized) or (len(endpoint_normalized) >= 5 and endpoint_normalized in alias)) for alias in aliases)


def _route_result(route: dict, direction: str, vehicles: list[dict]) -> dict:
    identifiers = {_normalise(str(route.get(key) or "")) for key in ("id", "ref", "name")}
    identifiers.discard("")
    matched_vehicles = [
        vehicle for vehicle in vehicles
        if _normalise(str(vehicle.get("route_id") or "")) in identifiers
    ]
    return {
        "id": route.get("id"),
        "name": route.get("name"),
        "ref": route.get("ref"),
        "from": route.get("from"),
        "to": route.get("to"),
        "boarding_stop": route.get("from") if direction == "forward" else route.get("to"),
        "destination_stop": route.get("to") if direction == "forward" else route.get("from"),
        "direction": direction,
        # OSM route metadata supplied to this app has no dependable stop sequence or timetable.
        "intermediate_stops": [],
        "travel_duration_minutes": None,
        "buses": matched_vehicles,
    }


def search_destinations(origin: str, destination: str, transit: dict, vehicle_result: dict | None = None) -> dict:
    stops = transit.get("stops") or []
    routes = transit.get("routes") or []
    origin_matches = _location_matches(origin, stops, routes)
    destination_matches = _location_matches(destination, stops, routes)
    if not origin_matches or not destination_matches:
        return {
            "status": "unmatched_locations",
            "message": "We couldn’t match one or both locations to mapped stops or route endpoints.",
            "origin": {"query": origin, "matches": origin_matches, "suggestions": _location_matches(origin, stops, routes)},
            "destination": {"query": destination, "matches": destination_matches, "suggestions": _location_matches(destination, stops, routes)},
            "routes": [], "alternatives": [], "route_features": {"type": "FeatureCollection", "features": []},
            "live_status": "not_checked", "live_message": "",
        }

    origin_endpoint = [
        route for route in routes
        if _endpoint_matches(route.get("from"), origin, origin_matches)
    ]
    destination_endpoint = [
        route for route in routes
        if _endpoint_matches(route.get("to"), destination, destination_matches)
    ]
    by_id = {route.get("id"): route for route in origin_endpoint if route.get("id")}
    direct = [route for route in destination_endpoint if route.get("id") in by_id]

    matched_vehicles = []
    vehicle_result = vehicle_result or {}
    if direct and vehicle_result.get("live") or direct and vehicle_result.get("status") == "stale":
        matched_route_ids = set()
        for route in direct:
            matched_route_ids.update(_normalise(str(route.get(key) or "")) for key in ("id", "ref", "name"))
        matched_vehicles = [
            vehicle for vehicle in vehicle_result.get("data", [])
            if _normalise(str(vehicle.get("route_id") or "")) in matched_route_ids
        ]
    live_status = vehicle_result.get("status", "not_configured") if direct else "not_checked"
    live_message = vehicle_result.get("message", "") if direct else ""
    stale = bool(vehicle_result.get("stale") or vehicle_result.get("status") == "stale")
    results = [_route_result(route, "forward", matched_vehicles) for route in direct]

    alternatives = []
    if not results:
        alternative_routes = {route.get("id"): route for route in origin_endpoint if route.get("id")}
        for route in destination_endpoint:
            if route.get("id"):
                alternative_routes.setdefault(route["id"], route)
        alternatives = [{
            "id": route.get("id"), "name": route.get("name"), "ref": route.get("ref"),
            "from": route.get("from"), "to": route.get("to"),
        } for route in list(alternative_routes.values())[:5]]

    route_ids = {route.get("id") for route in direct}
    features = (transit.get("route_features") or {}).get("features", [])
    selected_features = [feature for feature in features if feature.get("properties", {}).get("route_id") in route_ids]
    return {
        "status": "routes_found" if results else "no_direct_route",
        "message": "Direct mapped route matches found." if results else "No direct route found between these mapped locations.",
        "origin": {"query": origin, "matches": origin_matches, "suggestions": []},
        "destination": {"query": destination, "matches": destination_matches, "suggestions": []},
        "routes": results,
        "alternatives": alternatives,
        "route_features": {"type": "FeatureCollection", "features": selected_features},
        "live_status": live_status,
        "live_message": live_message,
        "live_stale": stale,
    }
