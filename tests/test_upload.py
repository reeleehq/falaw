"""``falaw.upload`` — content-keyed, TTL-bounded, injectable (falaw#87)."""

from __future__ import annotations

import pytest

from falaw import upload
from falaw.upload import default_upload_index


class _Uploader:
    def __init__(self):
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        return f"https://v3b.fal.media/files/{len(self.calls)}.png"


@pytest.fixture
def png(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(b"pixels")
    return p


def test_unchanged_file_uploads_once(png):
    up, idx = _Uploader(), {}
    assert upload(png, uploader=up, index=idx) == upload(png, uploader=up, index=idx)
    assert len(up.calls) == 1


def test_same_bytes_at_another_path_share_the_upload(png, tmp_path):
    twin = tmp_path / "b.png"
    twin.write_bytes(png.read_bytes())
    up, idx = _Uploader(), {}
    assert upload(png, uploader=up, index=idx) == upload(twin, uploader=up, index=idx)
    assert len(up.calls) == 1


def test_changed_bytes_upload_again(png):
    up, idx = _Uploader(), {}
    first = upload(png, uploader=up, index=idx)
    png.write_bytes(b"other pixels")
    assert upload(png, uploader=up, index=idx) != first
    assert len(up.calls) == 2


def test_entries_expire_after_ttl(png):
    up, idx, now = _Uploader(), {}, [1000.0]
    kw = dict(uploader=up, index=idx, ttl_s=60, clock=lambda: now[0])
    upload(png, **kw)
    now[0] += 59
    upload(png, **kw)
    assert len(up.calls) == 1
    now[0] += 2
    upload(png, **kw)
    assert len(up.calls) == 2


def test_default_index_persists_under_the_falaw_cache(png, tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))
    up = _Uploader()
    a = upload(png, uploader=up)
    assert upload(png, uploader=up) == a and len(up.calls) == 1
    assert len(list(default_upload_index())) == 1


def test_corrupt_or_foreign_index_entries_are_misses(png):
    from falaw.upload import file_digest

    up = _Uploader()
    for bad in ({"url": "u"}, "junk", {"url": 3, "uploaded_at": 0}):
        idx = {file_digest(png): bad}
        assert upload(png, uploader=up, index=idx).startswith("https://")
    assert len(up.calls) == 3


def test_unreadable_default_index_file_is_a_miss(png, tmp_path, monkeypatch):
    import os

    from falaw.upload import UPLOAD_INDEX_DIRNAME, file_digest

    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))
    root = tmp_path / "cache" / UPLOAD_INDEX_DIRNAME
    os.makedirs(root)
    (root / file_digest(png)).write_text('{"url": "htt')  # truncated mid-write
    up = _Uploader()
    upload(png, uploader=up)
    assert len(up.calls) == 1
    assert not [n for n in os.listdir(root) if n.endswith(".part")]


def test_a_failing_uploader_leaves_the_index_unchanged(png):
    idx = {}

    def boom(path):
        raise RuntimeError("network")

    with pytest.raises(RuntimeError):
        upload(png, uploader=boom, index=idx)
    assert idx == {}


def test_future_dated_entry_and_negative_ttl(png):
    from falaw.upload import file_digest

    up = _Uploader()
    idx = {file_digest(png): {"url": "https://x/y", "uploaded_at": 10**12}}
    upload(png, uploader=up, index=idx)
    assert len(up.calls) == 1  # clock-skewed entry not trusted
    with pytest.raises(ValueError):
        upload(png, uploader=up, index={}, ttl_s=-1)


def test_default_uploader_uses_the_bound_key_via_fal_client_for(png, monkeypatch):
    import importlib

    mod = importlib.import_module("falaw.upload")  # falaw.upload is the function

    seen = {}

    class _Client:
        def upload_file(self, path):
            seen["path"] = path
            return "https://v3b.fal.media/z"

    monkeypatch.setattr(
        mod,
        "fal_client_for",
        lambda api_key=None: seen.update(key=api_key) or _Client(),
    )
    assert upload(png, index={}, api_key="k") == "https://v3b.fal.media/z"
    assert seen == {"key": "k", "path": str(png)}
