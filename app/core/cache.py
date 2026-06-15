"""Simple in-memory cache with TTL support for performance optimization."""

import time
from typing import Any, Dict, Optional, TypeVar, Generic, Callable

T = TypeVar("T")


class CacheEntry(Generic[T]):
    """A cache entry with expiration time."""

    __slots__ = ("value", "expires_at")

    def __init__(self, value: T, ttl: float):
        self.value = value
        self.expires_at = time.time() + ttl

    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


class TTLCache(Generic[T]):
    """Thread-safe TTL cache with automatic expiration.

    Usage:
        cache = TTLCache[str](default_ttl=60.0)
        cache.set("key", "value")
        value = cache.get("key")  # Returns "value" if not expired, None otherwise
    """

    def __init__(self, default_ttl: float = 300.0):
        """Initialize cache with default TTL in seconds."""
        self.default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry[T]] = {}

    def get(self, key: str) -> Optional[T]:
        """Get value from cache if exists and not expired."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.is_expired():
            del self._cache[key]
            return None
        return entry.value

    def set(self, key: str, value: T, ttl: Optional[float] = None) -> None:
        """Set value in cache with optional TTL override."""
        ttl = ttl if ttl is not None else self.default_ttl
        self._cache[key] = CacheEntry(value, ttl)

    def delete(self, key: str) -> bool:
        """Delete key from cache. Returns True if key existed."""
        return self._cache.pop(key, None) is not None

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns number of entries removed."""
        before = len(self._cache)
        expired_keys = [k for k, v in self._cache.items() if v.is_expired()]
        for key in expired_keys:
            del self._cache[key]
        return before - len(self._cache)

    def get_or_compute(
        self,
        key: str,
        compute: Callable[[], T],
        ttl: Optional[float] = None,
    ) -> T:
        """Get from cache or compute and cache the result."""
        value = self.get(key)
        if value is not None:
            return value
        value = compute()
        self.set(key, value, ttl)
        return value

    def size(self) -> int:
        """Return number of cached entries (including expired)."""
        return len(self._cache)
