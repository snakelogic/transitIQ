"""Small process-safe SQLite snapshot cache for real upstream responses."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import OrderedDict
from pathlib import Path
from threading import RLock

_MEMORY_CACHE: OrderedDict[str, tuple[str, float]] = OrderedDict()
_MEMORY_CACHE_LOCK = RLock()
_MEMORY_CACHE_BYTES = 0
_MEMORY_CACHE_LIMIT = 32 * 1024 * 1024


def _use_memory() -> bool:
    return os.environ.get("TRANSIT_CACHE_BACKEND", "sqlite").lower() == "memory"


def _cache_path() -> Path:
    configured = os.environ.get("TRANSIT_CACHE_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent.parent / "instance" / "transit-cache.sqlite3"


def _connect() -> sqlite3.Connection:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS source_snapshots (
            cache_key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            saved_at REAL NOT NULL
        )
    """)
    return connection


def read_snapshot(cache_key: str) -> tuple[dict, float] | None:
    if _use_memory():
        with _MEMORY_CACHE_LOCK:
            entry = _MEMORY_CACHE.get(cache_key)
            if entry is not None:
                _MEMORY_CACHE.move_to_end(cache_key)
        if entry is None:
            return None
        try:
            return json.loads(entry[0]), entry[1]
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    try:
        with _connect() as connection:
            row = connection.execute(
                "SELECT payload, saved_at FROM source_snapshots WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0]), float(row[1])
    except (OSError, sqlite3.Error, json.JSONDecodeError, TypeError, ValueError):
        return None


def write_snapshot(cache_key: str, payload: dict, saved_at: float | None = None) -> None:
    if _use_memory():
        global _MEMORY_CACHE_BYTES
        try:
            serialized = json.dumps(payload, separators=(",", ":"))
            entry_bytes = len(serialized.encode("utf-8"))
            if entry_bytes > _MEMORY_CACHE_LIMIT:
                return
            with _MEMORY_CACHE_LOCK:
                previous = _MEMORY_CACHE.pop(cache_key, None)
                if previous:
                    _MEMORY_CACHE_BYTES -= len(previous[0].encode("utf-8"))
                _MEMORY_CACHE[cache_key] = (serialized, saved_at or time.time())
                _MEMORY_CACHE_BYTES += entry_bytes
                while _MEMORY_CACHE_BYTES > _MEMORY_CACHE_LIMIT:
                    _, removed = _MEMORY_CACHE.popitem(last=False)
                    _MEMORY_CACHE_BYTES -= len(removed[0].encode("utf-8"))
        except (TypeError, ValueError):
            return
        return
    try:
        with _connect() as connection:
            connection.execute(
                "INSERT INTO source_snapshots(cache_key, payload, saved_at) VALUES (?, ?, ?) "
                "ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload, saved_at=excluded.saved_at",
                (cache_key, json.dumps(payload, separators=(",", ":")), saved_at or time.time()),
            )
    except (OSError, sqlite3.Error, TypeError, ValueError):
        # Cache failure must never turn a healthy upstream response into an API failure.
        return
