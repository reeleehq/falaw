"""Tests for falaw.prune — cache capacity accounting and eviction (falaw#22).

The load-bearing assertions here are not "does it delete files" but:

* a prune is a **dry run** unless asked otherwise, and an unbounded one is
  refused rather than guessed at;
* ``rebillable_entries`` is *correct*, per area — it is the number a human
  reads before deciding to spend money, and each area computes it differently;
* an unprovable age is never treated as evidence of staleness.
"""

from __future__ import annotations

import json
import os
import time
from datetime import timedelta

import pytest

from falaw import cache, prune


# --- helpers ----------------------------------------------------------------


def _put_blob(data: bytes, *, age_s: float = 0.0) -> str:
    """Write ``data`` into the default content store; return its content hash."""
    from falaw.content import default_content_store

    store = default_content_store()
    content_hash = store.put_blob(data)
    if age_s:
        path = store.blob_path(content_hash)
        old = time.time() - age_s
        os.utime(path, (old, old))
    return content_hash


def _age_manifest(key_dir: str, age_s: float) -> None:
    """Rewrite an entry's ``stored_at`` to ``age_s`` seconds ago."""
    path = os.path.join(key_dir, "manifest.json")
    with open(path) as f:
        manifest = json.load(f)
    manifest["stored_at"] = time.time() - age_s
    with open(path, "w") as f:
        json.dump(manifest, f)


DAY = 86_400


# --- usage ------------------------------------------------------------------


ALL_AREAS = [
    "assets",
    "content",
    "manifests",
    "other",
    "scenes",
    "uploads",
    "url_index",
]


def _du(root: str) -> int:
    """Total bytes under ``root`` — an independent walk, not the code under test."""
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            total += os.path.getsize(os.path.join(dirpath, name))
    return total


def test_cache_usage_breaks_the_total_down_by_area():
    cache.cache_put("fal-ai/x", {"p": 1}, {"images": [{"url": "https://f/a.png"}]})
    _put_blob(b"some-blob-bytes")

    usage = prune.cache_usage()

    assert sorted(a.name for a in usage.areas) == ALL_AREAS
    assert usage.area("manifests").entries == 1
    assert usage.area("content").entries == 1
    assert usage.area("content").bytes >= len(b"some-blob-bytes")


def test_the_total_is_every_byte_under_the_root_not_just_the_areas_we_enumerated():
    """Under-reporting is the one direction a capacity tool cannot afford.

    Checked against an independent walk, because `total == sum(areas)` is a
    tautology over the implementation and cannot catch an unclaimed directory.
    """
    cache.cache_put("fal-ai/x", {"p": 1}, {"r": 1})
    _put_blob(b"blob-bytes")
    root = cache._cache_dir()
    # A directory no area knows about, and a stray file in an entry dir.
    os.makedirs(os.path.join(root, "some_future_feature"), exist_ok=True)
    with open(os.path.join(root, "some_future_feature", "big.bin"), "wb") as f:
        f.write(b"x" * 5000)

    usage = prune.cache_usage()

    assert usage.total_bytes == _du(root)
    assert usage.area("other").bytes >= 5000


def test_scenes_are_their_own_area_not_invisible():
    """falaw writes `scenes/` too; an area nobody enumerated is bytes nobody sees."""
    root = cache._cache_dir()
    os.makedirs(os.path.join(root, "scenes"), exist_ok=True)
    with open(os.path.join(root, "scenes", "my_scene.manifest.json"), "wb") as f:
        f.write(b"y" * 3000)

    usage = prune.cache_usage()

    assert usage.area("scenes").bytes == 3000
    assert usage.area("scenes").entries == 1
    # ... and it is not miscounted as a prunable cache entry.
    assert usage.area("manifests").entries == 0


def test_a_crashed_writes_part_file_is_visible_somewhere():
    """`.part` leftovers occupy the volume; invisible bytes fill a disk silently."""
    root = cache._cache_dir()
    entry_dir = cache.cache_put("fal-ai/x", {"p": 1}, {"r": 1})
    with open(os.path.join(entry_dir, "manifest.json.abc123.part"), "wb") as f:
        f.write(b"z" * 4000)

    usage = prune.cache_usage()

    assert usage.total_bytes == _du(root)
    assert usage.area("other").bytes >= 4000


def test_cache_stats_keeps_its_old_keys_and_gains_the_breakdown():
    """The whole point of #22: a total alone cannot tell you what is safe to drop."""
    cache.cache_put("fal-ai/x", {"p": 1}, {"r": 1})

    stats = cache.cache_stats()

    assert stats["manifest_entries"] == 1
    assert stats["size_bytes"] == _du(cache._cache_dir())
    assert sorted(stats["areas"]) == ALL_AREAS


def test_cache_usage_area_rejects_an_unknown_name():
    with pytest.raises(KeyError):
        prune.cache_usage().area("nope")


def test_no_area_reports_the_cache_root_as_its_own_directory():
    """`rmtree(area.path)` must never be able to take the content store with it."""
    usage = prune.cache_usage()
    root = os.path.realpath(usage.root)
    for area in usage.areas:
        if area.path is not None:
            assert os.path.realpath(area.path) != root, area.name
    assert usage.area("manifests").path is None


# --- the refusal ------------------------------------------------------------


@pytest.mark.parametrize(
    "fn", [prune.prune_content, prune.prune_manifests, prune.prune_assets]
)
def test_an_unbounded_prune_is_refused_not_guessed(fn):
    """'Everything' and 'nothing' are both plausible readings, and one re-bills the cache."""
    with pytest.raises(ValueError, match="needs a bound"):
        fn()


# --- content ----------------------------------------------------------------


def test_prune_content_dry_run_reports_without_deleting():
    content_hash = _put_blob(b"old-bytes", age_s=100 * DAY)
    from falaw.content import default_content_store

    report = prune.prune_content(older_than=90 * DAY)

    assert report.dry_run is True
    assert [c.key for c in report.candidates] == [content_hash]
    assert report.freed_bytes == len(b"old-bytes")
    # ... and the blob is still there.
    assert default_content_store().has_blob(content_hash)


def test_prune_content_deletes_when_told_to():
    content_hash = _put_blob(b"old-bytes", age_s=100 * DAY)
    from falaw.content import default_content_store

    report = prune.prune_content(older_than=90 * DAY, dry_run=False)

    assert report.dry_run is False
    assert report.errors == ()
    assert not default_content_store().has_blob(content_hash)


def test_prune_content_keeps_what_is_young_enough():
    young = _put_blob(b"young", age_s=1 * DAY)
    old = _put_blob(b"old-bytes", age_s=100 * DAY)

    report = prune.prune_content(older_than=90 * DAY)

    assert [c.key for c in report.candidates] == [old]
    assert report.kept_entries == 1
    assert young not in {c.key for c in report.candidates}


def test_prune_content_counts_the_entries_it_makes_unmaterializable():
    """The money number. An entry whose asset resolves to a dropped blob re-bills."""
    from falaw.content import content_ref_for_url

    url = "https://fal.media/files/doomed.png"
    # Register url -> content hash exactly as a real execute would, then record
    # a cache entry whose response names that URL.
    ref = content_ref_for_url(url, fetcher=lambda _u: [b"doomed-bytes"])
    cache.cache_put("fal-ai/x", {"p": 1}, {"images": [{"url": url}]})
    # A second entry that points at an asset we are NOT dropping.
    other = "https://fal.media/files/safe.png"
    content_ref_for_url(other, fetcher=lambda _u: [b"safe-bytes"])
    cache.cache_put("fal-ai/x", {"p": 2}, {"images": [{"url": other}]})

    from falaw.content import default_content_store

    store = default_content_store()
    os.utime(
        store.blob_path(ref.content_hash),
        (time.time() - 100 * DAY, time.time() - 100 * DAY),
    )

    report = prune.prune_content(older_than=90 * DAY)

    assert [c.key for c in report.candidates] == [ref.content_hash]
    assert report.rebillable_entries == 1, report.summary()


def test_prune_content_does_not_count_entries_that_were_already_broken():
    """An entry with no recoverable asset is not made worse by this prune."""
    cache.cache_put("fal-ai/x", {"p": 1}, {"text": "no asset here"})
    _put_blob(b"unrelated", age_s=100 * DAY)

    report = prune.prune_content(older_than=90 * DAY)

    assert len(report.candidates) == 1
    assert report.rebillable_entries == 0


def test_max_bytes_evicts_oldest_first_and_keeps_the_newest_under_budget():
    old = _put_blob(b"a" * 100, age_s=30 * DAY)
    mid = _put_blob(b"b" * 100, age_s=20 * DAY)
    new = _put_blob(b"c" * 100, age_s=1 * DAY)

    report = prune.prune_content(max_bytes=250)

    dropped = {c.key for c in report.candidates}
    assert dropped == {old}, report.summary()
    assert report.kept_entries == 2
    assert {mid, new} & dropped == set()


def test_max_bytes_never_evicts_a_newer_blob_while_keeping_an_older_one():
    """Sizes must differ, or oldest-first and greedy-keep-what-fits coincide.

    The failure this pins: a greedy scan over a newest-first list *skips* an
    item too big to fit and keeps going, so it deletes newer, larger blobs while
    retaining older, smaller ones behind them. On a media cache (an 8 MB clip
    beside 200 KB thumbnails) that is the ordinary case, and each large recent
    blob it drops is a candidate re-bill of the most expensive render.
    """
    big_new = _put_blob(b"a" * 500, age_s=1 * DAY)
    mid_5d = _put_blob(b"b" * 200, age_s=5 * DAY)
    mid_6d = _put_blob(b"c" * 200, age_s=6 * DAY)
    mid_7d = _put_blob(b"d" * 200, age_s=7 * DAY)
    old_100d = _put_blob(b"e" * 100, age_s=100 * DAY)
    old_200d = _put_blob(b"f" * 100, age_s=200 * DAY)

    report = prune.prune_content(max_bytes=800)

    ages = {
        big_new: 1,
        mid_5d: 5,
        mid_6d: 6,
        mid_7d: 7,
        old_100d: 100,
        old_200d: 200,
    }
    dropped = {c.key for c in report.candidates}
    kept = {c.key for c in report.candidates} ^ set(ages)
    youngest_dropped = min((ages[k] for k in dropped), default=10**9)
    oldest_kept = max((ages[k] for k in kept), default=0)
    assert oldest_kept < youngest_dropped, (
        f"kept a {oldest_kept}-day blob while dropping a "
        f"{youngest_dropped}-day one\n{report.summary()}"
    )
    assert report.kept_bytes <= 800


def test_max_bytes_frees_the_minimum_needed_to_reach_the_budget():
    """Eviction stops as soon as what remains fits; it is not a prefix wipe."""
    _put_blob(b"a" * 100, age_s=1 * DAY)
    _put_blob(b"b" * 100, age_s=2 * DAY)
    oldest = _put_blob(b"c" * 100, age_s=3 * DAY)

    report = prune.prune_content(max_bytes=200)

    assert [c.key for c in report.candidates] == [oldest]


def test_max_bytes_of_zero_drops_everything():
    a = _put_blob(b"a" * 10, age_s=DAY)
    b = _put_blob(b"b" * 10, age_s=DAY)

    report = prune.prune_content(max_bytes=0)

    assert {c.key for c in report.candidates} == {a, b}
    assert report.kept_entries == 0


def test_an_unprovable_age_is_never_evidence_of_staleness():
    """A backend with no filesystem path reports no mtime; that is not 'old'."""
    from lacing import ArtifactStore

    store = ArtifactStore.in_memory()
    store.put_blob(b"ageless")

    report = prune.prune_content(older_than=1, store=store)

    assert report.candidates == ()
    assert report.kept_entries == 1


def test_an_unprovable_age_is_evicted_last_under_a_size_bound():
    """Space may force the issue — but only after everything datable is gone."""
    from lacing import ArtifactStore

    store = ArtifactStore.in_memory()
    ageless = store.put_blob(b"x" * 100)

    report = prune.prune_content(max_bytes=100, store=store)

    # It fits, so it survives; nothing datable exists to drop ahead of it.
    assert report.candidates == ()
    assert report.kept_entries == 1

    report = prune.prune_content(max_bytes=0, store=store)
    assert [c.key for c in report.candidates] == [ageless]


# --- manifests --------------------------------------------------------------


def test_prune_manifests_rebills_every_entry_it_drops():
    entry_dir = cache.cache_put("fal-ai/x", {"p": 1}, {"r": 1})
    _age_manifest(entry_dir, 100 * DAY)

    report = prune.prune_manifests(older_than=90 * DAY)

    assert len(report.candidates) == 1
    assert report.rebillable_entries == 1


def test_prune_manifests_reads_stored_at_not_just_mtime():
    """The manifest records when falaw wrote it; a touched file must not read as new."""
    entry_dir = cache.cache_put("fal-ai/x", {"p": 1}, {"r": 1})
    _age_manifest(entry_dir, 100 * DAY)
    # mtime is *now* (we just rewrote the file), so an mtime-only implementation
    # would keep this entry.
    assert time.time() - os.path.getmtime(os.path.join(entry_dir, "manifest.json")) < 5

    report = prune.prune_manifests(older_than=90 * DAY)

    assert len(report.candidates) == 1


def test_prune_manifests_leaves_blobs_alone():
    """Blobs are shared by content hash across entries — the drop_cache_entry rule."""
    content_hash = _put_blob(b"shared-bytes")
    entry_dir = cache.cache_put("fal-ai/x", {"p": 1}, {"r": 1})
    _age_manifest(entry_dir, 100 * DAY)

    prune.prune_manifests(older_than=90 * DAY, dry_run=False)

    from falaw.content import default_content_store

    assert default_content_store().has_blob(content_hash)
    assert cache.cache_get("fal-ai/x", {"p": 1}) is None


# --- assets -----------------------------------------------------------------


def test_prune_assets_is_free_while_the_blob_survives():
    """The cheapest reclaim in the cache: a copy whose original is still there."""
    from falaw.content import content_ref_for_url

    url = "https://fal.media/files/a.png"
    content_ref_for_url(url, fetcher=lambda _u: [b"asset-bytes"])
    path = cache.materialize_asset(url)
    old = time.time() - 100 * DAY
    os.utime(path, (old, old))

    report = prune.prune_assets(older_than=90 * DAY)

    assert len(report.candidates) == 1
    assert report.rebillable_entries == 0, report.summary()


def test_prune_assets_flags_the_copies_whose_blob_is_gone():
    from falaw.content import content_ref_for_url, default_content_store

    url = "https://fal.media/files/a.png"
    ref = content_ref_for_url(url, fetcher=lambda _u: [b"asset-bytes"])
    path = cache.materialize_asset(url)
    old = time.time() - 100 * DAY
    os.utime(path, (old, old))
    del default_content_store().blobs[ref.content_hash]

    report = prune.prune_assets(older_than=90 * DAY)

    assert report.rebillable_entries == 1, report.summary()


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("a" * 64 + ".png", "a" * 64),
        ("hint-" + "b" * 64 + ".mp4", "b" * 64),
        ("nope.png", None),
        ("z" * 64 + ".png", None),  # not hex
        ("short.bin", None),
    ],
)
def test_content_hash_is_read_back_out_of_the_asset_filename(filename, expected):
    assert prune._content_hash_in_asset_name(filename) == expected


# --- failure handling -------------------------------------------------------


def test_a_failed_deletion_is_reported_not_raised(monkeypatch):
    """A prune that aborts halfway leaves neither the disk nor a report."""
    _put_blob(b"a" * 10, age_s=100 * DAY)
    _put_blob(b"b" * 10, age_s=100 * DAY)

    from falaw.content import default_content_store

    store = default_content_store()
    original = type(store.blobs).__delitem__
    calls = {"n": 0}

    def flaky(self, key):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("device busy")
        return original(self, key)

    monkeypatch.setattr(type(store.blobs), "__delitem__", flaky)

    report = prune.prune_content(older_than=90 * DAY, dry_run=False, store=store)

    assert len(report.errors) == 1
    assert "device busy" in report.errors[0]
    assert calls["n"] == 2, "the sweep must continue past a failure"


def test_freed_bytes_counts_what_was_deleted_not_what_was_selected(monkeypatch):
    """ "freed 2.4 GB" while nothing was freed is how a full disk stays full."""
    _put_blob(b"a" * 1000, age_s=100 * DAY)
    _put_blob(b"b" * 1000, age_s=100 * DAY)

    from falaw.content import default_content_store

    store = default_content_store()
    monkeypatch.setattr(
        type(store.blobs),
        "__delitem__",
        lambda self, key: (_ for _ in ()).throw(OSError("read-only file system")),
    )

    report = prune.prune_content(older_than=90 * DAY, dry_run=False, store=store)

    assert len(report.candidates) == 2
    assert len(report.errors) == 2
    assert report.freed_bytes == 0, report.summary()
    assert "FAILED" in report.summary()
    # ... and the blobs really are still there.
    assert len(list(default_content_store().blobs)) == 2


def test_a_blob_no_manifest_points_at_is_reported_not_called_free():
    """`materialize_asset` blobs have no fal response behind them.

    Counting only `rebillable_entries` reported such a prune as costing nothing
    while it destroyed the last copy of a reference image.
    """
    from falaw.content import content_ref_for_url, default_content_store

    ref = content_ref_for_url(
        "https://example.com/reference.png", fetcher=lambda _u: [b"reference-bytes"]
    )
    store = default_content_store()
    old = time.time() - 100 * DAY
    os.utime(store.blob_path(ref.content_hash), (old, old))

    report = prune.prune_content(older_than=90 * DAY)

    assert len(report.candidates) == 1
    assert report.rebillable_entries == 0  # correct: no cache entry re-bills
    assert report.unreferenced_candidates == 1, report.summary()
    assert "no cache entry behind them" in report.summary()


@pytest.mark.parametrize("bad", [0, -1, -86400, timedelta(0), timedelta(days=-1)])
def test_a_non_positive_older_than_is_refused(bad):
    """It arrives as `days * DAY` with a config-defaulted `days=0` — a full wipe."""
    _put_blob(b"a" * 10)
    with pytest.raises(ValueError, match="must be positive"):
        prune.prune_content(older_than=bad)


def test_a_negative_max_bytes_is_refused():
    with pytest.raises(ValueError, match="must be >= 0"):
        prune.prune_content(max_bytes=-1)


def test_prune_assets_leaves_in_flight_part_files_alone():
    """`write_blob_to_file` stages `.part` inside `assets/`; deleting it breaks the writer."""
    root = cache._cache_dir()
    assets = os.path.join(root, "assets")
    os.makedirs(assets, exist_ok=True)
    part = os.path.join(assets, "abc.png.deadbeef.part")
    with open(part, "wb") as f:
        f.write(b"in-flight")

    report = prune.prune_assets(max_bytes=0, dry_run=False)

    assert os.path.exists(part), report.summary()
    assert part not in {c.path for c in report.candidates}
    assert report.rebillable_entries == 0


def test_assets_usage_counts_exactly_what_prune_assets_can_reach():
    """Otherwise a `max_bytes` budget over the area can never converge."""
    root = cache._cache_dir()
    assets = os.path.join(root, "assets")
    os.makedirs(os.path.join(assets, "nested"), exist_ok=True)
    with open(os.path.join(assets, "nested", "deep.png"), "wb") as f:
        f.write(b"q" * 777)
    with open(os.path.join(assets, "a" * 64 + ".png"), "wb") as f:
        f.write(b"r" * 50)

    before = prune.cache_usage().area("assets").bytes
    prune.prune_assets(max_bytes=0, dry_run=False)
    after = prune.cache_usage().area("assets").bytes

    assert before == 50, "usage counted bytes prune cannot reach"
    assert after == 0


def test_unknown_age_is_ordered_last_among_several_candidates():
    """The ordering half of the rule — a single-candidate test cannot see it."""
    from lacing import ArtifactStore

    store = ArtifactStore.in_memory()
    ageless = store.put_blob(b"x" * 100)
    # A filesystem-backed store would give ages; in-memory gives none, so mix
    # by hand through _select to exercise ordering directly.
    dated = prune.PruneCandidate(
        key="dated", path="", bytes=100, last_modified=time.time() - 500 * DAY
    )
    unknown = prune.PruneCandidate(key=ageless, path="", bytes=100)

    doomed, survivors = prune._select(
        [unknown, dated], older_than=None, max_bytes=100, now=time.time()
    )

    assert [c.key for c in doomed] == ["dated"], "the datable one evicts first"
    assert [c.key for c in survivors] == [ageless]


def test_equal_ages_evict_deterministically():
    """Otherwise the choice falls through to filesystem listing order."""
    now = time.time()
    a = prune.PruneCandidate(key="aaa", path="", bytes=100, last_modified=now)
    b = prune.PruneCandidate(key="bbb", path="", bytes=100, last_modified=now)
    c = prune.PruneCandidate(key="ccc", path="", bytes=100, last_modified=now)

    forward, _ = prune._select([a, b, c], older_than=None, max_bytes=100, now=now)
    reverse, _ = prune._select([c, b, a], older_than=None, max_bytes=100, now=now)

    assert [x.key for x in forward] == [x.key for x in reverse]


def test_content_usage_counts_blobs_not_catalog_files():
    """`from_directory` lays down a `catalog/` falaw never writes."""
    root = cache._cache_dir()
    _put_blob(b"one")
    _put_blob(b"two")
    catalog = os.path.join(root, "content", "catalog")
    os.makedirs(catalog, exist_ok=True)
    with open(os.path.join(catalog, "stray.json"), "w") as f:
        f.write("{}")

    assert prune.cache_usage().area("content").entries == 2


def test_manifest_iteration_skips_the_named_areas():
    """A `manifest.json` inside an area directory is not a cache entry."""
    root = cache._cache_dir()
    cache.cache_put("fal-ai/x", {"p": 1}, {"r": 1})
    for area in ("content", "assets", "url_index", "scenes"):
        d = os.path.join(root, area, "sneaky")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "manifest.json"), "w") as f:
            f.write("{}")

    assert prune.cache_usage().area("manifests").entries == 1


def test_summary_says_would_when_it_is_a_dry_run():
    _put_blob(b"a" * 10, age_s=100 * DAY)

    dry = prune.prune_content(older_than=90 * DAY)
    assert "would free" in dry.summary()

    wet = prune.prune_content(older_than=90 * DAY, dry_run=False)
    assert "freed" in wet.summary() and "would free" not in wet.summary()


# --- containment and real deletion (falaw#66) --------------------------------


def test_prune_content_deletes_from_disk_not_to_the_trash(tmp_path, monkeypatch):
    """A trashed blob frees nothing on the volume while the report says it did."""
    import dol.trash

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))

    # dol falls back to os.remove where it finds no trash (macOS with a fake
    # HOME, Windows without pywin32), so an empty trash alone proves nothing
    # there. The trashing default must not even be reached.
    def _trash_default(path):
        raise AssertionError(f"dol's trash-by-default delete was used for {path}")

    monkeypatch.setattr(dol.trash, "default_delete_func", _trash_default)
    content_hash = _put_blob(b"old-bytes", age_s=100 * DAY)

    report = prune.prune_content(older_than=90 * DAY, dry_run=False)

    assert report.errors == ()
    assert [c.key for c in report.deleted] == [content_hash]
    trashed = [f for _, _, files in os.walk(home) for f in files]
    assert trashed == [], f"blob went to the trash instead of off the disk: {trashed}"


def test_prune_content_never_lists_or_deletes_outside_the_blob_root(tmp_path):
    """A symlinked directory in the blob root must not pull outside files in."""
    from falaw.content import default_content_store

    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "precious.bin"
    victim.write_bytes(b"not a blob")
    old = time.time() - 100 * DAY
    os.utime(victim, (old, old))

    store = default_content_store()
    try:
        os.symlink(outside, os.path.join(store.blobs.rootdir, "escape"))
    except (OSError, NotImplementedError):  # Windows without symlink privilege
        pytest.skip("cannot create symlinks here")
    content_hash = _put_blob(b"old-bytes", age_s=100 * DAY)

    # `max_bytes=0` selects everything listed, so an escaped file that got
    # listed (the raw `dol.Files` listing follows the link) would be deleted.
    report = prune.prune_content(max_bytes=0, dry_run=False, store=store)

    assert [c.key for c in report.candidates] == [content_hash]
    assert victim.read_bytes() == b"not a blob"
