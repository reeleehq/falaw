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
