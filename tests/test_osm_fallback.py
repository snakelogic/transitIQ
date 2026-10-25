from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.error import URLError

from transit.osm import TransitSourceError, _request_overpass


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
            self.assertEqual(_request_overpass(), {"elements": []})

        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(urlopen.call_args_list[0].args[0].full_url, "https://primary.example/interpreter")
        self.assertEqual(urlopen.call_args_list[1].args[0].full_url, "https://backup.example/interpreter")

    def test_all_unreachable_endpoints_return_clear_source_error(self):
        with patch.dict("os.environ", {
            "OVERPASS_URL": "https://primary.example/interpreter",
            "OVERPASS_FALLBACK_URLS": "https://backup.example/interpreter",
        }, clear=False), patch("transit.osm.urlopen", side_effect=URLError("network unreachable")):
            with self.assertRaisesRegex(TransitSourceError, "All configured OpenStreetMap Overpass endpoints failed"):
                _request_overpass()


if __name__ == "__main__":
    unittest.main()
