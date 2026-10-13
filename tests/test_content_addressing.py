"""Regression guards for falaw#14 — identify media by *what it is*, not *where*.

Two defects, one confusion:

* **D3** — ``Artifact.asset_id`` was ``sha256(url)``, so two byte-identical
  renders got different ids and ``lacing.Artifact``'s content-hash contract was
  false for every media artifact falaw produced.
* **D1** — the upstream *URL* went into the downstream cache key, so a
  byte-identical upstream regeneration missed downstream and re-billed a
  $0.35–$1.50 clip for work that had not changed.

fal's own docs are the primary source for why a URL cannot carry identity:
"Each upload produces a unique URL with no shared namespace" and "Expired files
are permanently deleted and cannot be recovered."

The load-bearing tests here are:

* :func:`test_same_bytes_at_a_new_url_hits_the_downstream_cache` — D1's fix.
* :func:`test_changed_upstream_bytes_miss_the_downstream_cache` — the other
  half: a key change must still *happen* when the input really changed, or the
  fix would trade a wasteful miss for a wrong hit.
* :func:`test_the_wire_gets_the_url_and_the_key_gets_the_content_hash` — the
  split that makes both possible without sending a content hash to fal.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import types

import pytest


IMG_A = b"\x89PNG-pretend-image-A" * 4
IMG_B = b"\x89PNG-pretend-image-B" * 4


# --- helpers ---------------------------------------------------------------


class FakeFal:
    """A fal_client stub whose asset URLs the test controls."""

    def __init__(self):
        self.calls: list[dict] = []
        self.next_image_url = "http://cdn/img-1.png"
        self.next_video_url = "http://cdn/clip-1.mp4"
        self.raise_on_call: BaseException | None = None

    def subscribe(self, application, *, arguments, with_logs, on_queue_update):
        self.calls.append({"application": application, "arguments": dict(arguments)})
        if self.raise_on_call is not None:
            raise self.raise_on_call
        if "svd" in application or "image-to-video" in application:
            return {
                "video": {
                    "url": self.next_video_url,
                    "duration": 3.0,
                    "content_type": "video/mp4",
                }
            }
        return {"images": [{"url": self.next_image_url, "content_type": "image/png"}]}

    @property
    def applications(self) -> list[str]:
        return [c["application"] for c in self.calls]


@pytest.fixture
def fal(monkeypatch):
    stub = FakeFal()
    monkeypatch.setitem(
        sys.modules,
        "fal_client",
        types.SimpleNamespace(
            InProgress=type("IP", (), {"__init__": lambda s, logs: None}),
            subscribe=stub.subscribe,
        ),
    )
    return stub


def _image_plan():
    from falaw import CallPlan, Plan

    return Plan(
        calls=(
            CallPlan(
                tool="generate_image",
                application="fal-ai/flux/dev",
                arguments={"prompt": "a tiger"},
                output_kind="image",
                estimated_cost_usd=0.02,
            ),
        )
    )


def _two_step_plan():
    from falaw import CallPlan, Plan

    return Plan(
        calls=(
            CallPlan(
                tool="generate_image",
                application="fal-ai/flux/dev",
                arguments={"prompt": "a tiger"},
                output_kind="image",
                estimated_cost_usd=0.02,
            ),
            CallPlan(
                tool="image_to_video",
                application="fal-ai/svd",
                arguments={"image_url": "<from 0>", "duration": 3},
                output_kind="video",
                estimated_cost_usd=0.50,
            ),
        )
    )


def _evict(call):
    """Drop one call's cache entry — the "another machine / after eviction" case."""
    from falaw.cache import _entry_dir, _key

    shutil.rmtree(
        _entry_dir(_key(call.application, call.arguments)), ignore_errors=True
    )


def _manifests() -> list[dict]:
    from falaw.cache import _cache_dir

    out = []
    for dirpath, _dirs, files in os.walk(_cache_dir()):
        for f in files:
            if f == "manifest.json":
                with open(os.path.join(dirpath, f)) as fh:
                    out.append(json.load(fh))
    return out


def _manifest_for(application: str) -> dict:
    matches = [m for m in _manifests() if m["application"] == application]
    assert len(matches) == 1, f"expected one manifest for {application}, got {matches}"
    return matches[0]


# --- D3: asset_id is the SHA-256 of the bytes ------------------------------


def test_asset_id_is_the_sha256_of_the_bytes(fal, fake_assets):
    from lacing import hash_bytes

    from falaw import execute_plan

    fal.next_image_url = "http://cdn/whatever.png"
    fake_assets.serve("http://cdn/whatever.png", IMG_A)

    (art,) = execute_plan(_image_plan())

    assert art.asset_id == hash_bytes(IMG_A)
    assert art.bytes_size == len(IMG_A)
    assert art.url == "http://cdn/whatever.png"  # kept as a hint
    # ... and NOT the hash of the URL (the defect).
    assert art.asset_id != hash_bytes(b"http://cdn/whatever.png")


def test_the_bytes_are_stored_and_reachable_from_the_artifact(fal, fake_assets):
    from falaw import execute_plan

    fal.next_image_url = "http://cdn/a.png"
    fake_assets.serve("http://cdn/a.png", IMG_A)

    (art,) = execute_plan(_image_plan())

    assert art.path is not None, "the artifact must point at the stored bytes"
    assert open(art.path, "rb").read() == IMG_A


def test_same_bytes_at_two_urls_are_one_artifact_identity(fal, fake_assets):
    from falaw import execute_plan

    fal.next_image_url = "http://cdn/first.png"
    fake_assets.serve("http://cdn/first.png", IMG_A)
    (first,) = execute_plan(_image_plan())

    _evict(_image_plan().calls[0])
    fal.next_image_url = "http://cdn/second.png"
    fake_assets.serve("http://cdn/second.png", IMG_A)
    (second,) = execute_plan(_image_plan())

    assert first.url != second.url
    assert first.asset_id == second.asset_id


def test_two_distinct_assets_get_distinct_asset_ids(fake_assets):
    """Different bytes ⇒ different ids; identical bytes ⇒ one shared id."""
    from lacing import ArtifactStore

    from falaw.content import content_ref_for_url

    store = ArtifactStore.in_memory()
    fake_assets.serve("http://cdn/x1", IMG_A)
    fake_assets.serve("http://cdn/x2", IMG_B)
    fake_assets.serve("http://cdn/x3", IMG_A)

    r1 = content_ref_for_url("http://cdn/x1", store=store)
    r2 = content_ref_for_url("http://cdn/x2", store=store)
    r3 = content_ref_for_url("http://cdn/x3", store=store)

    assert r1.content_hash != r2.content_hash
    assert r1.content_hash == r3.content_hash
    assert len(store.blobs) == 2, "identical bytes must dedup to one blob"


# --- D1: the downstream cache key is over content, not location -------------


def test_same_bytes_at_a_new_url_hits_the_downstream_cache(fal, fake_assets):
    """The money test.

    Run 1 caches both calls. Then the *upstream* entry is evicted (a second
    machine, a ``refresh``, a GC) so the upstream genuinely re-executes and fal
    mints a **new URL** for the **same bytes**. The expensive downstream clip
    must be served from cache — under the old URL-in-the-key behaviour it was
    re-rendered and re-billed.
    """
    from falaw import execute_plan

    plan = _two_step_plan()

    fal.next_image_url = "http://cdn/img-run1.png"
    fake_assets.serve("http://cdn/img-run1.png", IMG_A)
    fake_assets.serve("http://cdn/clip-1.mp4", b"clip-bytes")
    first = execute_plan(plan)
    assert fal.applications == ["fal-ai/flux/dev", "fal-ai/svd"]

    _evict(plan.calls[0])
    fal.calls.clear()
    fal.next_image_url = "http://cdn/img-run2.png"  # different location...
    fake_assets.serve("http://cdn/img-run2.png", IMG_A)  # ...identical bytes

    second = execute_plan(plan)

    assert fal.applications == ["fal-ai/flux/dev"], (
        "only the upstream should have re-executed; the downstream clip must "
        "hit the cache because its input bytes did not change"
    )
    assert second[0].asset_id == first[0].asset_id
    assert second[1].asset_id == first[1].asset_id


def test_changed_upstream_bytes_miss_the_downstream_cache(fal, fake_assets):
    """The safety half: a genuinely different input must NOT hit."""
    from falaw import execute_plan

    plan = _two_step_plan()

    fal.next_image_url = "http://cdn/img-run1.png"
    fake_assets.serve("http://cdn/img-run1.png", IMG_A)
    fake_assets.serve("http://cdn/clip-1.mp4", b"clip-bytes-1")
    execute_plan(plan)

    _evict(plan.calls[0])
    fal.calls.clear()
    fal.next_image_url = "http://cdn/img-run2.png"
    fake_assets.serve("http://cdn/img-run2.png", IMG_B)  # DIFFERENT bytes
    fal.next_video_url = "http://cdn/clip-2.mp4"
    fake_assets.serve("http://cdn/clip-2.mp4", b"clip-bytes-2")

    execute_plan(plan)

    assert fal.applications == ["fal-ai/flux/dev", "fal-ai/svd"], (
        "a changed upstream input must change the downstream key"
    )


def test_the_wire_gets_the_url_and_the_key_gets_the_content_hash(fal, fake_assets):
    """The split. Sending a content hash to fal would break every chained call."""
    from lacing import hash_bytes

    from falaw import execute_plan
    from falaw.plan import CONTENT_REF_PREFIX

    plan = _two_step_plan()
    fal.next_image_url = "http://cdn/img.png"
    fake_assets.serve("http://cdn/img.png", IMG_A)
    fake_assets.serve("http://cdn/clip-1.mp4", b"clip-bytes")

    execute_plan(plan)

    wire = fal.calls[1]["arguments"]
    assert wire["image_url"] == "http://cdn/img.png"
    assert not wire["image_url"].startswith(CONTENT_REF_PREFIX)

    manifest = _manifest_for("fal-ai/svd")
    assert manifest["arguments"]["image_url"] == (
        f"{CONTENT_REF_PREFIX}{hash_bytes(IMG_A)}"
    )
    assert manifest["wire_arguments"]["image_url"] == "http://cdn/img.png"


def test_unchained_calls_record_no_separate_wire_arguments(fal, fake_assets):
    """No placeholders ⇒ wire and key arguments are the same object."""
    from falaw import execute_plan

    fal.next_image_url = "http://cdn/a.png"
    execute_plan(_image_plan())

    assert "wire_arguments" not in _manifest_for("fal-ai/flux/dev")


def test_key_ref_prefers_content_and_falls_back_to_url():
    """Unit-level statement of the key-resolution rule."""
    from lacing import Artifact

    from falaw.plan import CONTENT_REF_PREFIX, _key_ref

    with_bytes = Artifact.from_bytes(
        IMG_A, kind="image", was_generated_by="agent:t", was_attributed_to="user:t"
    ).model_copy(update={"url": "http://cdn/a.png"})
    assert _key_ref(with_bytes, 0, "<from 0>") == (
        f"{CONTENT_REF_PREFIX}{with_bytes.asset_id}"
    )

    without_bytes = with_bytes.model_copy(update={"bytes_size": 0})
    assert _key_ref(without_bytes, 0, "<from 0>") == "http://cdn/a.png"

    nothing = without_bytes.model_copy(update={"url": None})
    with pytest.raises(ValueError):
        _key_ref(nothing, 0, "<from 0>")


# --- durability: fal deletes URLs -------------------------------------------


def test_stored_bytes_survive_an_expired_url(fal, fake_assets):
    """A months-old cache hit must still yield a usable artifact."""
    from falaw import execute_plan

    fal.next_image_url = "http://cdn/ephemeral.png"
    fake_assets.serve("http://cdn/ephemeral.png", IMG_A)
    (first,) = execute_plan(_image_plan())

    fake_assets.fail("http://cdn/ephemeral.png")  # fal deleted it
    fake_assets.fetched.clear()

    with pytest.warns(
        UserWarning, match="is gone from its origin|could not be re-read"
    ):
        (again,) = execute_plan(_image_plan())

    # `http://cdn/...` is not a fal host, so falaw asks the origin before
    # reusing the stored bytes (falaw#23) — and falls back to them when the
    # origin is gone, which is the guarantee this test exists for. The
    # no-request-at-all version of this property is the fal-URL test below.
    assert fake_assets.fetched == ["http://cdn/ephemeral.png"]
    assert again.asset_id == first.asset_id
    assert again.bytes_size == len(IMG_A)


def test_an_expired_fal_url_costs_no_request_at_all(fal, fake_assets):
    """The production shape of the property above.

    fal mints a URL per upload, so its hint can be trusted outright: the
    months-old hit is served from the store with **zero** requests. This is what
    keeps re-executing a 200-shot plan free, and it is why falaw#23's
    revalidation is scoped to hosts falaw does not know to be immutable.
    """
    from falaw import execute_plan

    fal.next_image_url = "https://v3b.fal.media/files/ephemeral.png"
    fake_assets.serve("https://v3b.fal.media/files/ephemeral.png", IMG_A)
    (first,) = execute_plan(_image_plan())

    fake_assets.fail("https://v3b.fal.media/files/ephemeral.png")
    fake_assets.fetched.clear()

    (again,) = execute_plan(_image_plan())

    assert fake_assets.fetched == [], "a fal URL's hint needs no revalidation"
    assert again.asset_id == first.asset_id
    assert again.bytes_size == len(IMG_A)


def _strand_the_cache_entry(fal, fake_assets, *, drop_url_index=True):
    """Leave a cache entry whose recorded asset can no longer be read.

    The exact shape of a cassette recorded months ago: the fal response is
    still on disk, but this machine has no blob for it and fal has deleted the
    URL. Returns the stranded URL.
    """
    from falaw import execute_plan
    from falaw.cache import _cache_dir
    from falaw.content import CONTENT_STORE_DIRNAME, URL_INDEX_DIRNAME

    url = fal.next_image_url
    fake_assets.serve(url, IMG_A)
    execute_plan(_image_plan())

    shutil.rmtree(os.path.join(_cache_dir(), CONTENT_STORE_DIRNAME))
    if drop_url_index:
        shutil.rmtree(os.path.join(_cache_dir(), URL_INDEX_DIRNAME))
    fake_assets.fail(url)
    return url


def test_an_unreadable_cache_entry_is_dropped_and_the_call_re_executed(
    fal, fake_assets
):
    """A cache must never become a trap.

    An entry whose recorded asset can no longer be read is *unusable*, and no
    number of retries against the cache will change that. Treating it as a hard
    failure leaves the caller only one escape — ``use_cache=False``, which
    re-bills the whole plan instead of the one dead call. So: drop it, warn,
    re-execute. (Regression guard for the adversarial review of falaw#14.)
    """
    from falaw import execute_plan

    fal.next_image_url = "http://cdn/ephemeral.png"
    _strand_the_cache_entry(fal, fake_assets)
    calls_before = len(fal.calls)

    # The re-execution mints a fresh, live URL — as a real fal re-run does.
    fal.next_image_url = "http://cdn/reborn.png"
    fake_assets.serve("http://cdn/reborn.png", IMG_A)

    with pytest.warns(UserWarning, match="Dropping the falaw cache entry"):
        (again,) = execute_plan(_image_plan())

    assert len(fal.calls) == calls_before + 1, "the dead entry must force a re-run"
    assert again.bytes_size == len(IMG_A)
    assert again.asset_id == hashlib.sha256(IMG_A).hexdigest()


def test_a_dropped_cache_entry_stays_dropped(fal, fake_assets):
    """The self-heal must actually heal: the third run is a hit again.

    Without :func:`falaw.cache.drop_cache_entry` actually removing the
    manifest, every subsequent run would re-pay — a silent, permanent leak that
    a single-run test cannot see.
    """
    from falaw import execute_plan

    fal.next_image_url = "http://cdn/ephemeral.png"
    _strand_the_cache_entry(fal, fake_assets)

    fal.next_image_url = "http://cdn/reborn.png"
    fake_assets.serve("http://cdn/reborn.png", IMG_A)
    with pytest.warns(UserWarning):
        execute_plan(_image_plan())
    calls_after_heal = len(fal.calls)

    execute_plan(_image_plan())

    assert len(fal.calls) == calls_after_heal, "the healed entry must now hit"


def test_a_dropped_entry_is_gone_even_when_the_re_execution_fails(fal, fake_assets):
    """The drop must be a real deletion, not a no-op masked by the rewrite.

    On the happy path the re-execution immediately re-writes the manifest under
    the same key, so removing it is invisible — a ``drop_cache_entry`` that
    only *pretends* to delete passes every other test here. It becomes visible
    exactly when the re-execution **fails**: without a real deletion the
    poisoned entry survives, and the next run replays the same dead response
    instead of starting from a clean miss.
    """
    from falaw import execute_plan
    from falaw.cache import cache_get

    fal.next_image_url = "http://cdn/ephemeral.png"
    _strand_the_cache_entry(fal, fake_assets)

    boom = RuntimeError("fal is down")
    fal.raise_on_call = boom

    with pytest.warns(UserWarning, match="Dropping the falaw cache entry"):
        with pytest.raises(RuntimeError):
            execute_plan(_image_plan())

    assert cache_get("fal-ai/flux/dev", _image_plan().calls[0].arguments) is None, (
        "the unusable entry must be gone, not merely re-warned about"
    )


def test_a_usable_cache_entry_is_never_dropped(fal, fake_assets):
    """The inverse guard: stored bytes mean the entry is fine, dead URL or not.

    Without this, "drop unreadable entries" could degenerate into "drop every
    entry", which would re-bill everything while still looking green.
    """
    from falaw import execute_plan

    fal.next_image_url = "http://cdn/ephemeral.png"
    fake_assets.serve("http://cdn/ephemeral.png", IMG_A)
    execute_plan(_image_plan())
    calls_before = len(fal.calls)

    fake_assets.fail("http://cdn/ephemeral.png")  # URL dead, blob still here
    execute_plan(_image_plan())

    assert len(fal.calls) == calls_before, "a materializable entry must still hit"


def test_a_remembered_hash_without_its_blob_is_refetched(fal, fake_assets):
    """The url→hash index is a *hint*, never a substitute for the bytes.

    Trusting it without checking the blob is present would hand out an
    ``asset_id`` backed by nothing — a content address that addresses no
    content — the moment a blob is GC'd or the store moves.
    """
    from falaw import execute_plan
    from falaw.cache import _cache_dir
    from falaw.content import CONTENT_STORE_DIRNAME

    fal.next_image_url = "http://cdn/x.png"
    fake_assets.serve("http://cdn/x.png", IMG_A)
    (first,) = execute_plan(_image_plan())

    # Blobs gone (GC / different machine); the url-index hint survives.
    shutil.rmtree(os.path.join(_cache_dir(), CONTENT_STORE_DIRNAME))
    fake_assets.fetched.clear()

    (again,) = execute_plan(_image_plan())

    assert fake_assets.fetched == ["http://cdn/x.png"]
    assert again.asset_id == first.asset_id
    assert open(again.path, "rb").read() == IMG_A


def test_a_remembered_hash_with_neither_blob_nor_live_url_is_not_trusted(
    fal, fake_assets
):
    """A hint whose blob is gone and whose URL is dead must not become an id.

    The remembered hash is *right* — but nothing can produce those bytes, so
    handing it out would be a content address that addresses no content.
    """
    from falaw import execute_plan
    from falaw.cache import _cache_dir
    from falaw.content import CONTENT_STORE_DIRNAME

    fal.next_image_url = "http://cdn/x.png"
    fake_assets.serve("http://cdn/x.png", IMG_A)
    (first,) = execute_plan(_image_plan())

    shutil.rmtree(os.path.join(_cache_dir(), CONTENT_STORE_DIRNAME))
    fake_assets.fail("http://cdn/x.png")

    with pytest.warns(UserWarning):
        (again,) = execute_plan(_image_plan())

    assert again.bytes_size == 0
    assert again.asset_id != first.asset_id, (
        "a hash with no bytes behind it must not be presented as the content id"
    )


def test_a_fresh_result_whose_bytes_are_unreadable_degrades_loudly(fal, fake_assets):
    """fal already billed this render — never discard it over a failed download.

    Raising here would turn a transient network blip into a lost paid result.
    The honest answer is a URL-only artifact that *says* it has no content
    identity (``bytes_size == 0``), plus a warning.
    """
    from falaw import execute_plan

    fal.next_image_url = "http://cdn/unreachable.png"
    fake_assets.fail("http://cdn/unreachable.png")

    with pytest.warns(UserWarning, match="URL-only artifact"):
        (art,) = execute_plan(_image_plan(), use_cache=False)

    assert art.url == "http://cdn/unreachable.png"
    assert art.bytes_size == 0
    assert art.path is None


def test_a_degraded_artifact_never_claims_a_url_hash_as_its_content_id(
    fal, fake_assets
):
    """The degraded id must not be ``sha256(url)`` — that is the D3 defect.

    A URL hash is 64 hex chars, so it satisfies every structural check while
    being exactly the wrong value; the failure has to be visible in the
    *value*, not just the shape.
    """
    from lacing import hash_bytes

    from falaw import execute_plan

    fal.next_image_url = "http://cdn/unreachable.png"
    fake_assets.fail("http://cdn/unreachable.png")

    with pytest.warns(UserWarning):
        (art,) = execute_plan(_image_plan(), use_cache=False)

    assert art.asset_id != hash_bytes(b"http://cdn/unreachable.png")


def test_an_empty_asset_is_never_recorded_as_valid_media(fal, fake_assets):
    """Zero bytes is not "some bytes" — it must not become a content hash.

    ``sha256(b"")`` is a perfectly well-formed digest, which is what makes this
    dangerous: it would silently unify every empty response into one artifact.
    """
    from falaw import execute_plan
    from falaw.errors import FalAssetFetchError

    fal.next_image_url = "http://cdn/empty.png"
    fake_assets.serve("http://cdn/empty.png", b"")

    with pytest.warns(UserWarning):
        (art,) = execute_plan(_image_plan(), use_cache=False)

    assert art.bytes_size == 0
    assert art.asset_id != hashlib.sha256(b"").hexdigest()

    # The bytes-level API has nothing to degrade to, so it still raises.
    from falaw.content import content_ref_for_url

    with pytest.raises(FalAssetFetchError):
        content_ref_for_url("http://cdn/empty.png")


# --- the documented opt-out -------------------------------------------------


def test_fetch_bytes_false_downloads_nothing_and_forfeits_chained_caching(
    fal, fake_assets
):
    from lacing import hash_bytes

    from falaw import execute_plan
    from falaw.plan import CONTENT_REF_PREFIX

    plan = _two_step_plan()
    fal.next_image_url = "http://cdn/img.png"

    artifacts = execute_plan(plan, fetch_bytes=False)

    assert fake_assets.fetched == []
    assert artifacts[0].bytes_size == 0
    assert artifacts[0].path is None
    # Emphatically not sha256(url) — that was the defect, not the fallback.
    assert artifacts[0].asset_id != hash_bytes(b"http://cdn/img.png")

    manifest = _manifest_for("fal-ai/svd")
    key_ref = manifest["arguments"]["image_url"]
    assert key_ref == "http://cdn/img.png"
    assert not key_ref.startswith(CONTENT_REF_PREFIX)


def test_fetch_bytes_env_var_flips_the_default(fal, fake_assets, monkeypatch):
    from falaw import execute_plan
    from falaw.plan import FETCH_BYTES_ENVVAR

    monkeypatch.setenv(FETCH_BYTES_ENVVAR, "0")
    fal.next_image_url = "http://cdn/img.png"

    (art,) = execute_plan(_image_plan())

    assert fake_assets.fetched == []
    assert art.bytes_size == 0


# --- one addressing scheme: materialize_asset -------------------------------


def test_materialize_asset_is_addressed_by_content(fake_assets):
    from lacing import hash_bytes

    from falaw import materialize_asset

    fake_assets.serve("http://cdn/one.mp4", IMG_A)
    fake_assets.serve("http://cdn/two.mp4", IMG_A)

    p1 = materialize_asset("http://cdn/one.mp4")
    p2 = materialize_asset("http://cdn/two.mp4")

    assert os.path.basename(p1) == f"{hash_bytes(IMG_A)}.mp4"
    assert p1 == p2, "identical bytes at two URLs must resolve to one local file"
    assert open(p1, "rb").read() == IMG_A


def test_materialize_asset_does_not_refetch_stored_bytes(fake_assets):
    from falaw import materialize_asset

    fake_assets.serve("http://cdn/one.mp4", IMG_A)
    materialize_asset("http://cdn/one.mp4")
    fake_assets.fetched.clear()

    materialize_asset("http://cdn/one.mp4")

    assert fake_assets.fetched == []


def test_materialized_files_cannot_corrupt_the_content_store(fake_assets):
    """The returned path must not be the store blob's own inode.

    A hard link would make them one file, so any consumer writing through the
    returned path (ffmpeg in place, a stray ``open(p, "ab")``) leaves a blob
    whose SHA-256 no longer matches its name — while ``has_blob`` keeps saying
    ``True``. The store would then serve *wrong bytes under a correct content
    address*, which is the exact failure content addressing exists to prevent.
    """
    from lacing import hash_bytes

    from falaw import materialize_asset
    from falaw.content import default_content_store

    fake_assets.serve("http://cdn/clip.mp4", IMG_A)
    path = materialize_asset("http://cdn/clip.mp4")

    store = default_content_store()
    blob = store.blob_path(hash_bytes(IMG_A))
    assert blob is not None
    assert os.stat(path).st_ino != os.stat(blob).st_ino, "must be a copy, not a link"

    with open(path, "ab") as f:
        f.write(b"CORRUPTED-DOWNSTREAM")

    assert store.get_blob(hash_bytes(IMG_A)) == IMG_A, (
        "the content store must be unaffected by writes through a materialized file"
    )


def test_materialize_asset_short_circuits_on_an_existing_local_file(fake_assets):
    """Circle 1: the file is here, so neither store nor network is consulted.

    The content store is prunable and fal URLs expire, so a materialized file
    can easily outlive both. Requiring the hash to be *re-derivable* before
    returning a file that is sitting right there turns a free call into a
    failure.
    """
    import shutil as _shutil

    from falaw import materialize_asset
    from falaw.cache import _cache_dir
    from falaw.content import CONTENT_STORE_DIRNAME

    fake_assets.serve("http://cdn/clip.mp4", IMG_A)
    first = materialize_asset("http://cdn/clip.mp4")

    _shutil.rmtree(os.path.join(_cache_dir(), CONTENT_STORE_DIRNAME))  # pruned
    fake_assets.fail("http://cdn/clip.mp4")  # expired
    fake_assets.fetched.clear()

    with pytest.warns(
        UserWarning, match="is gone from its origin|could not be re-read"
    ):
        again = materialize_asset("http://cdn/clip.mp4")

    assert again == first
    assert open(again, "rb").read() == IMG_A
    # For a mutable URL circle 1 is a *fallback*, not a shortcut: falaw asks the
    # origin first (falaw#23 — returning the old file while a newer one is one
    # request away is the bug) and returns the local copy once that fails.
    assert fake_assets.fetched == ["http://cdn/clip.mp4"]


def test_materialize_asset_short_circuits_without_a_request_for_a_fal_url(fake_assets):
    """Circle 1 stays a pure shortcut where the hint is trustworthy."""
    import shutil as _shutil

    from falaw import materialize_asset
    from falaw.cache import _cache_dir
    from falaw.content import CONTENT_STORE_DIRNAME

    url = "https://v3b.fal.media/files/clip.mp4"
    fake_assets.serve(url, IMG_A)
    first = materialize_asset(url)

    _shutil.rmtree(os.path.join(_cache_dir(), CONTENT_STORE_DIRNAME))  # pruned
    fake_assets.fail(url)  # expired
    fake_assets.fetched.clear()

    again = materialize_asset(url)

    assert again == first
    assert open(again, "rb").read() == IMG_A
    assert fake_assets.fetched == []


def test_a_mutable_url_that_changed_yields_the_new_bytes(fake_assets):
    """falaw#23, the whole point: a changed input must change the content address.

    This is the exact scenario the issue reproduced. It used to return IMG_A
    forever with zero network access — a changed input producing an unchanged
    content hash, which then flowed into ``Artifact.asset_id`` and every
    downstream cache key. No ``refresh=`` needed: falaw revalidates on its own,
    because a caller who has to *know* their URL is mutable is a caller who will
    eventually forget.
    """
    from lacing import hash_bytes

    from falaw import materialize_asset

    fake_assets.serve("http://host/reference.png", IMG_A)
    before = materialize_asset("http://host/reference.png")
    assert open(before, "rb").read() == IMG_A

    fake_assets.serve("http://host/reference.png", IMG_B)  # changed behind us
    after = materialize_asset("http://host/reference.png")

    assert open(after, "rb").read() == IMG_B
    assert os.path.basename(after).startswith(hash_bytes(IMG_B))
    assert after != before, "a changed asset must get a new content address"


def test_an_unchanged_mutable_url_is_revalidated_not_re_downloaded(fake_assets):
    """The cheap half: one conditional request, no payload, same hash.

    Without this, host-scoping alone would make every reference image a full
    download on every call — correct, but the reason the issue called ETag
    revalidation "the right end state" rather than a nice-to-have.
    """
    from falaw import materialize_asset

    fake_assets.serve("http://host/reference.png", IMG_A)
    first = materialize_asset("http://host/reference.png")
    fake_assets.fetched.clear()

    again = materialize_asset("http://host/reference.png")

    assert again == first
    assert fake_assets.fetched == [], "a 304 must not transfer the body"


def test_refresh_still_forces_a_re_read(fake_assets):
    """The escape hatch survives, for an origin that lies about its validators."""
    from falaw import materialize_asset

    fake_assets.serve("http://host/reference.png", IMG_A)
    materialize_asset("http://host/reference.png")
    fake_assets.fetched.clear()

    materialize_asset("http://host/reference.png", refresh=True)

    assert fake_assets.fetched == ["http://host/reference.png"]


def test_materialize_asset_uses_its_injected_fetcher(fake_assets):
    """The transport seam must reach ``materialize_asset`` too.

    It is the entry point downstream packages call directly (for ffmpeg /
    PIL input), so an injection that only works through ``execute`` leaves
    the most-used path stuck on the network.
    """
    from lacing import hash_bytes

    from falaw import materialize_asset

    seen = []

    def fetcher(url):
        seen.append(url)
        return [IMG_B]

    path = materialize_asset("http://cdn/only-via-fetcher.png", fetcher=fetcher)

    assert seen == ["http://cdn/only-via-fetcher.png"]
    assert fake_assets.fetched == []
    assert os.path.basename(path) == f"{hash_bytes(IMG_B)}.png"
    assert open(path, "rb").read() == IMG_B


def test_materialize_asset_keeps_the_key_hint_prefix(fake_assets):
    from lacing import hash_bytes

    from falaw import materialize_asset

    fake_assets.serve("http://cdn/one.png", IMG_A)
    path = materialize_asset("http://cdn/one.png", key_hint="ref")
    assert os.path.basename(path) == f"ref-{hash_bytes(IMG_A)}.png"


# --- injection seams: they must work, or be refused -------------------------


def test_a_custom_converter_refuses_built_in_converter_knobs(fal, fake_assets):
    """Accepting a knob a custom converter cannot honour is worse than useless.

    ``content_store`` / ``fetch_bytes`` / ``asset_fetcher`` configure the
    built-in converter. Silently ignoring them means a caller who points falaw
    at a shared S3 content store *and* supplies a converter gets an empty store
    and no clue why.
    """
    from lacing import ArtifactStore

    from falaw import execute_plan

    def conv(raw, call):
        raise AssertionError("must never be reached")

    for kwargs in (
        {"content_store": ArtifactStore.in_memory()},
        {"fetch_bytes": True},
        {"asset_fetcher": lambda url: [b"x"]},
    ):
        with pytest.raises(ValueError, match="cannot be combined with"):
            execute_plan(_image_plan(), artifact_converter=conv, **kwargs)


def test_the_asset_fetcher_seam_replaces_the_network(fal, fake_assets):
    """The public seam a hermetic downstream suite is meant to use.

    Without it, the only ways to keep an offline suite offline are patching a
    private (``falaw.content._http_chunks``) or turning content addressing off
    entirely — so the suite stops exercising the thing under test.
    """
    from lacing import hash_bytes

    from falaw import execute_plan

    seen = []

    def fetcher(url):
        seen.append(url)
        return [IMG_B]

    fal.next_image_url = "http://cdn/whatever.png"
    (art,) = execute_plan(_image_plan(), asset_fetcher=fetcher)

    assert seen == ["http://cdn/whatever.png"]
    assert fake_assets.fetched == [], "the injected fetcher must be the only transport"
    assert art.asset_id == hash_bytes(IMG_B)


def test_an_injected_content_store_actually_receives_the_bytes(fal, fake_assets):
    from lacing import ArtifactStore, hash_bytes

    from falaw import execute_plan

    store = ArtifactStore.in_memory()
    fal.next_image_url = "http://cdn/into-store.png"
    fake_assets.serve("http://cdn/into-store.png", IMG_A)

    (art,) = execute_plan(_image_plan(), content_store=store)

    assert store.has_blob(hash_bytes(IMG_A))
    assert art.asset_id == hash_bytes(IMG_A)


# --- the module's own examples must run -------------------------------------


def test_content_module_doctests_pass():
    import doctest

    import falaw.content

    result = doctest.testmod(
        falaw.content,
        optionflags=doctest.NORMALIZE_WHITESPACE | doctest.ELLIPSIS,
    )
    assert result.failed == 0
