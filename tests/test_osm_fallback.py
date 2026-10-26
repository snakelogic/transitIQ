from __future__ import annotations

import unittest
import time
from unittest.mock import patch
from urllib.error import URLError

from transit import osm


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b'{"elements": []}'


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
