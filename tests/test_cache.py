"""Tests for the content-addressed cache."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))
    from falaw.journal import _default_journal

    _default_journal.cache_clear()
    yield
    _default_journal.cache_clear()


def test_cache_put_get_roundtrip():
    from falaw import cache

    raw = {"images": [{"url": "http://x/img.png"}]}
    cache.cache_put("fal-ai/flux/dev", {"prompt": "p"}, raw, note="test")
    hit = cache.cache_get("fal-ai/flux/dev", {"prompt": "p"})
    assert hit == raw


def test_cache_miss_returns_none():
    from falaw.cache import cache_get

    assert cache_get("fal-ai/nope", {"prompt": "x"}) is None


def test_cache_keyed_by_arguments():
    from falaw import cache

    cache.cache_put("fal-ai/flux/dev", {"prompt": "a"}, {"raw": 1})
    cache.cache_put("fal-ai/flux/dev", {"prompt": "b"}, {"raw": 2})
    assert cache.cache_get("fal-ai/flux/dev", {"prompt": "a"}) == {"raw": 1}
    assert cache.cache_get("fal-ai/flux/dev", {"prompt": "b"}) == {"raw": 2}


def test_cache_argument_order_invariant():
    """Equivalent arguments in different dict order should hit the same key."""
    from falaw import cache

    cache.cache_put("m", {"a": 1, "b": 2}, {"raw": "stored"})
    hit = cache.cache_get("m", {"b": 2, "a": 1})
    assert hit == {"raw": "stored"}


def test_cached_call_fal_returns_hit_without_calling(monkeypatch):
    from falaw import cache

    cache.cache_put("fal-ai/x", {"k": 1}, {"raw": "cached"})
    # If the cache works, this should not actually invoke fal_client.
    import fal_client

    def must_not_call(*a, **kw):
        raise AssertionError("fal_client.subscribe should not have been called")

    monkeypatch.setattr(fal_client, "subscribe", must_not_call)
    out = cache.cached_call_fal("fal-ai/x", {"k": 1})
    assert out == {"raw": "cached"}


def test_cached_call_fal_falls_through_on_miss(monkeypatch):
    from falaw import cache
    import fal_client

    def fake(application, *, arguments, **_kw):
        return {"images": [{"url": "http://x/i.png"}]}

    monkeypatch.setattr(fal_client, "subscribe", fake)
    out1 = cache.cached_call_fal("fal-ai/y", {"prompt": "fresh"})
    assert out1["images"][0]["url"] == "http://x/i.png"
    # Second call should hit the cache; replace fake with one that errors.
    monkeypatch.setattr(
        fal_client,
        "subscribe",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("re-call")),
    )
    out2 = cache.cached_call_fal("fal-ai/y", {"prompt": "fresh"})
    assert out2 == out1


def test_cached_call_fal_refresh_bypasses_cache(monkeypatch):
    from falaw import cache
    import fal_client

    cache.cache_put("fal-ai/z", {"k": 1}, {"raw": "old"})
    monkeypatch.setattr(fal_client, "subscribe", lambda *a, **kw: {"raw": "new"})
    out = cache.cached_call_fal("fal-ai/z", {"k": 1}, refresh=True)
    assert out == {"raw": "new"}
    # And the cache is now updated.
    assert cache.cache_get("fal-ai/z", {"k": 1}) == {"raw": "new"}


def test_cache_stats_reports_entries():
    from falaw import cache

    cache.cache_put("a", {"x": 1}, {"r": 1})
    cache.cache_put("a", {"x": 2}, {"r": 2})
    s = cache.cache_stats()
    assert s["manifest_entries"] == 2
    assert s["size_bytes"] > 0
