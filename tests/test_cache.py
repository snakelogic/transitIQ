from __future__ import annotations

import unittest
from unittest.mock import patch

from transit.cache import read_snapshot, write_snapshot


class MemoryTransitCacheTests(unittest.TestCase):
    def test_memory_backend_round_trips_payload_and_timestamp(self):
        cache_key = "test-memory-snapshot"
        payload = {"routes": [{"id": "r1"}]}
        with patch.dict("os.environ", {"TRANSIT_CACHE_BACKEND": "memory"}):
            write_snapshot(cache_key, payload, saved_at=123.0)
            self.assertEqual(read_snapshot(cache_key), (payload, 123.0))


if __name__ == "__main__":
    unittest.main()
