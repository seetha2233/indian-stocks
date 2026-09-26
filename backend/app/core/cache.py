"""Small TTL cache: Redis when it's reachable, otherwise in-process memory.

    @cached(ttl=60)
    def expensive(arg): ...

Values must be JSON-serialisable (they are API responses).

Keys include a data version that the pipeline bumps (bump_data_version) after
each step, so a refresh invalidates every cached response at once, in Redis
and in the API process's memory alike. The API re-reads the version at most
every VERSION_CHECK_SECONDS.
"""

import functools
import json
import threading
import time
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import text

from app.core.config import settings
from app.db.database import engine


META_TABLE = "app_meta"

VERSION_CHECK_SECONDS = 10

# How often the memory cache drops expired entries (e.g. old data versions)
SWEEP_SECONDS = 60


class MemoryCache:

    backend = "memory"

    def __init__(self):
        self._data: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self._swept = time.time()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires, value = item
            if expires < time.time():
                del self._data[key]
                return None
            return json.loads(value)

    def set(self, key: str, value: Any, ttl: int) -> None:
        with self._lock:
            now = time.time()
            if now - self._swept >= SWEEP_SECONDS:
                self._data = {k: v for k, v in self._data.items() if v[0] >= now}
                self._swept = now
            self._data[key] = (now + ttl, json.dumps(value, default=str))

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class RedisCache:

    backend = "redis"

    def __init__(self, client):
        self._r = client

    def get(self, key: str) -> Any | None:
        value = self._r.get(key)
        return None if value is None else json.loads(value)

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._r.setex(key, ttl, json.dumps(value, default=str))

    def clear(self) -> None:
        for key in self._r.scan_iter("cache:*"):
            self._r.delete(key)


def _connect():

    try:
        import redis

        client = redis.Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=0.5
        )
        client.ping()
        return RedisCache(client)

    except Exception:
        return MemoryCache()


cache = _connect()


_version = {"value": "", "checked": 0.0}


def data_version() -> str:
    """Current data version ("" before the first bump or without a DB)."""

    now = time.time()

    if now - _version["checked"] >= VERSION_CHECK_SECONDS:

        try:
            with engine.connect() as conn:
                value = conn.execute(
                    text(f"SELECT value FROM {META_TABLE} WHERE key = 'data_version'")
                ).scalar()
        except Exception:
            value = None

        _version.update(value=value or "", checked=now)

    return _version["value"]


def bump_data_version() -> str:
    """Invalidate every cached response; call after new data is written."""

    version = datetime.now().isoformat()

    with engine.begin() as conn:
        conn.execute(text(
            f"CREATE TABLE IF NOT EXISTS {META_TABLE} "
            f"(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        ))
        conn.execute(
            text(
                f"INSERT INTO {META_TABLE} (key, value) VALUES ('data_version', :v) "
                f"ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ),
            {"v": version}
        )

    # Old-version keys can't be hit any more; free them now (Redis) rather
    # than at their TTL
    cache.clear()
    _version.update(value=version, checked=time.time())

    return version


def cached(ttl: int) -> Callable:

    def decorator(fn: Callable) -> Callable:

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):

            key = f"cache:{data_version()}:{fn.__qualname__}:" + json.dumps(
                [args, kwargs], default=str, sort_keys=True
            )

            hit = cache.get(key)
            if hit is not None:
                return hit

            value = fn(*args, **kwargs)
            cache.set(key, value, ttl)
            return value

        return wrapper

    return decorator
