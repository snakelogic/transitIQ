from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app


class DestinationSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-not-for-production",
            "CUSTOMER_DATABASE": str(Path(self.temp_dir.name) / "customers.sqlite3"),
            "SESSION_COOKIE_SECURE": False,
        })
        self.client = app.test_client()
        self.transit = {
            "stops": [
                {"id": "node/1", "name": "Alpha Terminal", "ref": "A-01", "lat": 28.61, "lon": 77.20},
                {"id": "node/2", "name": "Market Square", "ref": "M-02", "lat": 28.62, "lon": 77.21},
                {"id": "node/3", "name": "Airport Road", "ref": "AR", "lat": 28.63, "lon": 77.22},
            ],
            "routes": [
                {"id": "relation/11", "name": "Alpha–Market Express", "ref": "A1", "from": "Alpha Terminal", "to": "Market Square"},
                {"id": "relation/12", "name": "Alpha–Airport Connector", "ref": "A2", "from": "Alpha Terminal", "to": "Airport Road"},
            ],
            "route_features": {"type": "FeatureCollection", "features": [
                {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[77.20, 28.61], [77.21, 28.62]]}, "properties": {"route_id": "relation/11", "name": "Alpha–Market Express", "ref": "A1"}},
                {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[77.20, 28.61], [77.22, 28.63]]}, "properties": {"route_id": "relation/12", "name": "Alpha–Airport Connector", "ref": "A2"}},
            ]},
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_locations_return_matching_route_geometry_and_matching_live_bus(self):
        vehicles = {"status": "connected", "live": True, "data": [
            {"id": "bus-1", "label": "Bus 501", "route_id": "A1", "lat": 28.615, "lon": 77.205},
            {"id": "bus-2", "label": "Bus 502", "route_id": "OTHER", "lat": 28.6, "lon": 77.1},
        ]}
        with patch("transit.routes.get_transit_data", return_value=self.transit), patch(
            "transit.routes.get_vehicle_positions", return_value=vehicles
        ):
            response = self.client.get("/api/v1/directions?from=Alpha%20Terminal&to=Market%20Square")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "routes_found")
        self.assertEqual(len(payload["routes"]), 1)
        route = payload["routes"][0]
        self.assertEqual(route["ref"], "A1")
        self.assertEqual(route["boarding_stop"], "Alpha Terminal")
        self.assertEqual(route["destination_stop"], "Market Square")
        self.assertEqual([bus["label"] for bus in route["buses"]], ["Bus 501"])
        self.assertIsNone(route["travel_duration_minutes"])
        self.assertEqual(route["intermediate_stops"], [])
        self.assertEqual({feature["properties"]["route_id"] for feature in payload["route_features"]["features"]}, {"relation/11"})

    def test_partial_stop_names_resolve_against_real_stop_names(self):
        with patch("transit.routes.get_transit_data", return_value=self.transit), patch(
            "transit.routes.get_vehicle_positions", return_value={"status": "key_required", "live": False, "data": [], "message": "API key needed"}
        ):
            response = self.client.get("/api/v1/directions?from=Alpha&to=Market")
        self.assertEqual(response.get_json()["status"], "routes_found")

    def test_invalid_location_is_reported_without_inventing_results(self):
        with patch("transit.routes.get_transit_data", return_value=self.transit):
            response = self.client.get("/api/v1/directions?from=Atlantis&to=Market%20Square")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "unmatched_locations")
        self.assertEqual(payload["origin"]["matches"], [])
        self.assertEqual(payload["routes"], [])

    def test_empty_fields_and_oversized_location_are_rejected(self):
        missing = self.client.get("/api/v1/directions?from=Alpha")
        oversized = self.client.get("/api/v1/directions?from=" + "x" * 121 + "&to=Market")
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.get_json()["error"]["code"], "locations_required")
        self.assertEqual(oversized.status_code, 400)
        self.assertEqual(oversized.get_json()["error"]["code"], "location_too_long")

    def test_valid_locations_with_no_direct_route_return_real_alternatives(self):
        with patch("transit.routes.get_transit_data", return_value=self.transit):
            unmatched = self.client.get("/api/v1/directions?from=Market%20Square&to=Airport%20Road")
        result = unmatched.get_json()
        self.assertEqual(result["status"], "no_direct_route")
        self.assertEqual(result["routes"], [])
        self.assertEqual([route["ref"] for route in result["alternatives"]], ["A2"])


if __name__ == "__main__":
    unittest.main()
