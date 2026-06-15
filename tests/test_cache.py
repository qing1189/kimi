"""Tests for TTL cache."""

import time
import pytest
from app.core.cache import TTLCache


def test_cache_set_and_get():
    cache = TTLCache[str](default_ttl=60.0)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"


def test_cache_get_nonexistent():
    cache = TTLCache[str]()
    assert cache.get("nonexistent") is None


def test_cache_expiration():
    cache = TTLCache[str](default_ttl=0.1)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"
    time.sleep(0.15)
    assert cache.get("key1") is None


def test_cache_custom_ttl():
    cache = TTLCache[str](default_ttl=60.0)
    cache.set("key1", "value1", ttl=0.1)
    assert cache.get("key1") == "value1"
    time.sleep(0.15)
    assert cache.get("key1") is None


def test_cache_delete():
    cache = TTLCache[str]()
    cache.set("key1", "value1")
    assert cache.delete("key1") is True
    assert cache.get("key1") is None
    assert cache.delete("key1") is False


def test_cache_clear():
    cache = TTLCache[str]()
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.clear()
    assert cache.get("key1") is None
    assert cache.get("key2") is None


def test_cache_cleanup_expired():
    cache = TTLCache[str](default_ttl=0.1)
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    time.sleep(0.15)
    removed = cache.cleanup_expired()
    assert removed == 2
    assert cache.size() == 0


def test_cache_get_or_compute():
    cache = TTLCache[int]()
    call_count = 0

    def compute():
        nonlocal call_count
        call_count += 1
        return 42

    # First call computes
    result1 = cache.get_or_compute("key1", compute)
    assert result1 == 42
    assert call_count == 1

    # Second call uses cache
    result2 = cache.get_or_compute("key1", compute)
    assert result2 == 42
    assert call_count == 1


def test_cache_size():
    cache = TTLCache[str]()
    assert cache.size() == 0
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    assert cache.size() == 2
