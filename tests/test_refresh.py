"""Offline tests for falaw.refresh.

We don't hit the network here. Network behavior is verified via the CLI
(`python -m falaw refresh-llms`) and by the conditional GET we already
confirmed against fal.ai (HTTP 304 with the saved ETag).
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_DATA_DIR", str(tmp_path))
    from falaw.journal import _default_journal

    _default_journal.cache_clear()
    yield
    _default_journal.cache_clear()


def test_parse_index_dedups_and_filters(tmp_path):
    from falaw.refresh import _parse_index

    idx = tmp_path / "idx.md"
    idx.write_text(
        "# fal\n\n## Docs\n\n"
        "- [a](https://fal.ai/docs/x.md)\n"
        "- [b](https://fal.ai/docs/y.md)\n"
        "  - nested [c](https://fal.ai/docs/z.md)\n"
        "- [a-dup](https://fal.ai/docs/x.md)\n"
        "- [bad](https://example.com/other.md)\n"
        "- [no-md](https://fal.ai/docs/missing-suffix)\n"
    )
    urls = _parse_index(str(idx))
    assert urls == [
        "https://fal.ai/docs/x.md",
        "https://fal.ai/docs/y.md",
        "https://fal.ai/docs/z.md",
    ]


def test_conditional_headers_uses_saved_state():
    from falaw.refresh import DocSource, _conditional_headers

    src = DocSource(name="x", url="http://x", local_path="/tmp/x")
    state = {"x": {"etag": '"abc"', "last_modified": "Sat, 02 May 2026 08:00:00 GMT"}}
    h = _conditional_headers(src, state)
    assert h["If-None-Match"] == '"abc"'
    assert h["If-Modified-Since"] == "Sat, 02 May 2026 08:00:00 GMT"


def test_conditional_headers_empty_when_no_state():
    from falaw.refresh import DocSource, _conditional_headers

    src = DocSource(name="x", url="http://x", local_path="/tmp/x")
    assert _conditional_headers(src, {}) == {}


def test_diff_against_previous_returns_unified_diff(tmp_path):
    from falaw.refresh import DocSource, _snapshot_path, diff_against_previous

    src = DocSource(name="d", url="http://x", local_path=str(tmp_path / "d.txt"))
    prev = _snapshot_path(src.name)
    os.makedirs(os.path.dirname(prev), exist_ok=True)
    with open(prev, "w") as f:
        f.write("a\nb\nc\n")
    with open(src.local_path, "w") as f:
        f.write("a\nB\nc\n")
    diff = diff_against_previous(src)
    assert "-b" in diff and "+B" in diff


def test_state_roundtrip():
    from falaw.refresh import _load_state, _save_state

    assert _load_state() == {}
    _save_state({"llms": {"etag": '"x"', "fetched_at": 1.0}})
    assert _load_state()["llms"]["etag"] == '"x"'


def test_refresh_tools_registered():
    from falaw.registry import list_tools

    names = {t.name for t in list_tools(tag="refresh")}
    assert "refresh_llms" in names
    assert "refresh_full_docs" in names


def test_fetch_if_changed_handles_304(monkeypatch, tmp_path):
    from falaw import refresh as r

    src = r.DocSource(
        name="t",
        url="http://example/t.txt",
        local_path=str(tmp_path / "t.txt"),
    )

    def fake_request(url, *, method="GET", extra_headers=None, timeout=30.0):
        return 304, {}, b""

    monkeypatch.setattr(r, "_request", fake_request)
    changed, body = r.fetch_if_changed(src)
    assert changed is False and body == ""
    # No file was created, no state was written.
    assert not os.path.exists(src.local_path)


def test_fetch_if_changed_writes_on_200(monkeypatch, tmp_path):
    from falaw import refresh as r

    src = r.DocSource(
        name="u",
        url="http://example/u.txt",
        local_path=str(tmp_path / "u.txt"),
    )
    headers = {"etag": '"new"', "last-modified": "now"}

    def fake_request(url, *, method="GET", extra_headers=None, timeout=30.0):
        return 200, headers, b"hello"

    monkeypatch.setattr(r, "_request", fake_request)
    changed, body = r.fetch_if_changed(src)
    assert changed is True and body == "hello"
    assert open(src.local_path).read() == "hello"
    state = r._load_state()
    assert state["u"]["etag"] == '"new"'
