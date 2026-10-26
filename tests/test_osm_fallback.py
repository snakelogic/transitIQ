from __future__ import annotations

import unittest
import time
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

from transit import osm


class FakeResponse:
    def __init__(self, payload=b'{"elements": []}'):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


class OverpassFallbackTests(unittest.TestCase):
    def test_network_failure_uses_configured_fallback_endpoint(self):
        with patch.dict("os.environ", {
            "OVERPASS_URL": "https://primary.example/interpreter",
            "OVERPASS_FALLBACK_URLS": "https://backup.example/interpreter",
        }, clear=False), patch("transit.osm.urlopen", side_effect=[URLError("network unreachable"), FakeResponse()]) as urlopen:
            self.assertEqual(osm._request_overpass(), {"elements": []})

        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(urlopen.call_args_list[0].args[0].full_url, "https://primary.example/interpreter")
        self.assertEqual(urlopen.call_args_list[1].args[0].full_url, "https://backup.example/interpreter")
        self.assertEqual(urlopen.call_args_list[0].kwargs["timeout"], osm.OVERPASS_REQUEST_TIMEOUT_SECONDS)

    def test_all_unreachable_endpoints_return_clear_source_error(self):
        with patch.dict("os.environ", {
            "OVERPASS_URL": "https://primary.example/interpreter",
            "OVERPASS_FALLBACK_URLS": "https://backup.example/interpreter",
        }, clear=False), patch("transit.osm.urlopen", side_effect=URLError("network unreachable")) as urlopen:
            with self.assertRaisesRegex(osm.TransitSourceError, "All configured OpenStreetMap Overpass endpoints failed") as error:
                osm._request_overpass()
        self.assertIn(osm.THIRD_OVERPASS_URL, str(error.exception))
        self.assertEqual(urlopen.call_count, 5)

    def test_geometry_timeout_falls_back_to_real_stops_and_route_metadata(self):
        payload = b'{"elements": [{"type": "node", "id": 7, "lat": 28.6, "lon": 77.2, "tags": {"highway": "bus_stop", "name": "Central Stop"}}, {"type": "relation", "id": 8, "tags": {"type": "route", "route": "bus", "name": "Route A", "from": "Central Stop", "to": "North Stop"}}]}'
        gateway_timeout = HTTPError(
            osm.THIRD_OVERPASS_URL, 504, "Gateway Timeout", {}, None
        )
        with patch.dict("os.environ", {
            "OVERPASS_URL": osm.THIRD_OVERPASS_URL,
            "OVERPASS_FALLBACK_URLS": "",
        }, clear=False), patch("transit.osm.urlopen", side_effect=[
            gateway_timeout,
            URLError("network unreachable"),
            URLError("network unreachable"),
            FakeResponse(payload),
        ]) as urlopen:
            normalized = osm._normalise(osm._request_overpass())

        self.assertEqual(normalized["counts"], {"stops": 1, "routes": 1})
        self.assertFalse(normalized["route_geometry_available"])
        self.assertEqual(normalized["stops"][0]["name"], "Central Stop")
        self.assertEqual(normalized["routes"][0]["name"], "Route A")
        self.assertEqual(urlopen.call_count, 4)
        query = parse_qs(urlopen.call_args_list[-1].args[0].data.decode())["data"][0]
        self.assertIn("out tags center;", query)

    def test_parallel_cold_requests_do_not_launch_duplicate_upstream_calls(self):
        with patch.object(osm, "read_snapshot", return_value=None), \
             patch.object(osm, "_cache", {"payload": None, "expires": 0}), \
             patch.object(osm, "_refreshing", True):
            with self.assertRaisesRegex(osm.TransitSourceError, "already in progress"):
                osm.get_transit_data()

    def test_failed_refresh_cooldown_prevents_immediate_retry(self):
        with patch.object(osm, "read_snapshot", return_value=None), \
             patch.object(osm, "_cache", {"payload": None, "expires": 0}), \
             patch.object(osm, "_refreshing", False), \
             patch.object(osm, "_retry_after", time.time() + 30), \
             patch.object(osm, "_request_overpass") as request:
            with self.assertRaisesRegex(osm.TransitSourceError, "temporarily unavailable"):
                osm.get_transit_data()
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
