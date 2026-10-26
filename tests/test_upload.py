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


def _fake_fal(monkeypatch, seen):
    import importlib
    import types

    mod = importlib.import_module("falaw.upload")  # falaw.upload is the function

    class _Client:
        def upload_file(self, path, lifecycle=None):
            seen.update(path=path, lifecycle=lifecycle)
            return "https://v3b.fal.media/z"

    monkeypatch.setattr(
        mod,
        "fal_client_for",
        lambda api_key=None: seen.update(key=api_key) or _Client(),
    )
    monkeypatch.setattr(
        "falaw.errors.import_fal_client",
        lambda: types.SimpleNamespace(
            StorageSettings=lambda expires_in: ("life", expires_in)
        ),
    )
    return mod


def test_default_uploader_uses_the_bound_key_and_makes_ttl_a_guarantee(
    png, monkeypatch
):
    seen = {}
    _fake_fal(monkeypatch, seen)
    assert upload(png, index={}, api_key="k", ttl_s=600) == "https://v3b.fal.media/z"
    assert seen == {"key": "k", "path": str(png), "lifecycle": ("life", 600)}


def test_namespaces_keep_backends_apart_in_a_shared_index(png):
    idx = {}
    a = upload(png, uploader=lambda p: "https://s3/a", index=idx, namespace="s3")
    b = upload(png, uploader=lambda p: "https://other/b", index=idx, namespace="other")
    assert (a, b) == ("https://s3/a", "https://other/b")
    assert upload(png, uploader=lambda p: "never", index=idx, namespace="s3") == a


def test_using_uploader_replaces_the_transfer_process_wide(png):
    from falaw import using_uploader

    with using_uploader(lambda p: "https://fake/x"):
        assert upload(png, index={}) == "https://fake/x"


# --- local files inside a Plan (falaw#92) -----------------------------------------


@pytest.fixture
def fal_calls(monkeypatch, tmp_path):
    """Isolated cache; the vendor call recorded, the uploader a counting fake."""
    from falaw import using_uploader

    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))
    sent, uploads = [], []

    def fake_call_fal(application, arguments, *, on_event=None, **kw):
        sent.append(dict(arguments))
        return {"video": {"url": "https://v3b.fal.media/files/v.mp4"}}

    monkeypatch.setattr("falaw.core.call_fal", fake_call_fal)

    def fake_upload(path):
        uploads.append(path)
        return f"https://v3b.fal.media/up/{len(uploads)}.png"

    with using_uploader(fake_upload):
        yield sent, uploads


def _plan(png, **kw):
    import falaw

    cp = falaw.make_call_plan(
        tool="image_to_video",
        application="fal-ai/x/i2v",
        arguments={"image_url": png, "prompt": "go"},
        output_kind="video",
        **kw,
    )
    return cp, falaw.Plan(calls=(cp,))


def test_a_path_argument_keeps_the_plan_pure_data(png, tmp_path):
    import os

    import falaw

    import hashlib

    cp, plan = _plan(png, consult_cache=False)
    digest = hashlib.sha256(png.read_bytes()).hexdigest()
    assert cp.arguments["image_url"] == f"<file sha256:{digest} {os.path.abspath(png)}>"
    assert cp.local_files == (("image_url",),)
    assert falaw.plan_from_dict(falaw.plan_to_dict(plan)).calls[0] == cp


def test_execute_uploads_on_the_wire_and_keys_on_the_bytes(png, fal_calls):
    import falaw
    from falaw.cache import cache_get

    sent, uploads = fal_calls
    cp, plan = _plan(png)
    assert cp.cache_status == "miss"
    falaw.execute_plan(plan)
    assert sent[0]["image_url"].startswith("https://v3b.fal.media/up/")
    assert uploads == [str(png)]
    # keyed on the content hash, not the path or the URL
    import hashlib

    digest = hashlib.sha256(png.read_bytes()).hexdigest()
    assert cache_get("fal-ai/x/i2v", {"image_url": f"sha256:{digest}", "prompt": "go"})


def test_a_cache_hit_does_not_upload_and_an_edited_file_misses(png, fal_calls):
    import falaw

    sent, uploads = fal_calls
    falaw.execute_plan(_plan(png)[1])
    cp, plan = _plan(png)
    assert cp.cache_status == "hit"  # the plan-time peek keys on the bytes too
    falaw.execute_plan(plan)
    assert len(sent) == 1 and len(uploads) == 1  # served from cache, no second upload
    png.write_bytes(b"edited pixels")
    cp2, plan2 = _plan(png)
    assert cp2.cache_status == "miss"
    falaw.execute_plan(plan2)
    assert len(sent) == 2 and len(uploads) == 2


# --- prune_uploads ----------------------------------------------------------------


def test_prune_uploads_is_bounded_dry_run_by_default_and_never_rebills(
    png, tmp_path, monkeypatch
):
    import os
    import time

    import falaw

    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))
    up = _Uploader()
    upload(png, uploader=up)
    entry = next((tmp_path / "cache" / "uploads").iterdir())
    old = time.time() - 3 * 86400
    os.utime(entry, (old, old))
    with pytest.raises(ValueError, match="needs a bound"):
        falaw.prune_uploads()
    dry = falaw.prune_uploads(older_than=86400)
    assert dry.dry_run and len(dry.candidates) == 1 and entry.exists()
    assert dry.rebillable_entries == 0
    kept = falaw.prune_uploads(older_than=10 * 86400, dry_run=False)
    assert kept.deleted == () and entry.exists()
    real = falaw.prune_uploads(older_than=86400, dry_run=False)
    assert len(real.deleted) == 1 and not entry.exists()
    assert falaw.cache_usage().areas  # the uploads area is reported


def test_a_string_that_looks_like_a_marker_is_inert_text(tmp_path, fal_calls):
    """Only declared pointers resolve: a hostile or accidental prompt cannot make
    falaw read and upload a file."""
    import falaw

    sent, uploads = fal_calls
    secret = tmp_path / "secret.txt"
    secret.write_text("s3cret")
    import hashlib

    lookalike = f"<file sha256:{hashlib.sha256(b's3cret').hexdigest()} {secret}>"
    cp = falaw.make_call_plan(
        tool="image_to_video",
        application="fal-ai/x/i2v",
        arguments={"prompt": lookalike},
        output_kind="video",
    )
    assert cp.local_files == ()
    falaw.execute_plan(falaw.Plan(calls=(cp,)))
    assert uploads == [] and sent[0]["prompt"] == lookalike


def test_plan_identity_follows_the_files_content(png):
    import falaw

    h1 = falaw.plan_hash(_plan(png, consult_cache=False)[1])
    png.write_bytes(b"edited")
    assert falaw.plan_hash(_plan(png, consult_cache=False)[1]) != h1


def test_a_missing_file_is_refused_while_planning_is_free(tmp_path):
    with pytest.raises(FileNotFoundError):
        _plan(tmp_path / "nope.png", consult_cache=False)


def test_a_file_edited_after_planning_is_refused_not_mis_keyed(png, fal_calls):
    import falaw

    sent, uploads = fal_calls
    _, plan = _plan(png)
    png.write_bytes(b"changed after planning")
    with pytest.raises(ValueError, match="changed since the Plan was made"):
        falaw.execute_plan(plan)
    assert sent == [] and uploads == []


def test_a_short_lifetime_upload_is_not_trusted_past_its_expiry(png):
    idx, now = {}, [1000.0]
    kw = dict(index=idx, clock=lambda: now[0], namespace="fal")
    upload(png, uploader=lambda p: "https://x/1", **kw)
    key = next(iter(idx))
    idx[key]["expires_at"] = 1060.0  # as a ttl_s=60 fal upload would record
    now[0] = 1100.0
    up = _Uploader()
    upload(png, uploader=up, **kw)
    assert len(up.calls) == 1  # re-uploaded: the remembered URL is dead


def test_anonymous_custom_uploaders_do_not_share_a_namespace(png):
    from falaw import using_uploader

    idx = {}

    def fake(p):
        return "https://fake/x"

    def s3(p):
        return "https://s3/x"

    with using_uploader(fake):
        assert upload(png, index=idx) == "https://fake/x"
    with using_uploader(s3):
        assert upload(png, index=idx) == "https://s3/x"
