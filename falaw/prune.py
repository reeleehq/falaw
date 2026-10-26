"""Capacity management for the falaw cache: see what is on disk, and reclaim it.

Before thorwhalen/falaw#14 the cache held kilobyte JSON manifests. It now
content-addresses every media result, so it also holds the **bytes** of every
generated image, clip and audio track. On any machine that has rendered a real
project that is gigabytes, and on the production box (a 40 GB volume) it is a
capacity question rather than a cosmetic one.

Nothing here runs automatically, and that is the design rather than an omission.
**Deleting a blob is a spending decision**: :func:`falaw.plan.execute` treats a
cache entry it cannot turn back into bytes as a *miss* and re-executes it, so
disk reclaimed today is re-billed the next time that beat renders. Every prune
is therefore ``dry_run=True`` by default and returns a :class:`PruneReport`
that says — before anything is removed — how many cache entries the prune would
put back on the invoice.

The cache has six areas, with very different economics — and only one of them
is genuinely cheap to reclaim:

``manifests``
    The fal responses, keyed by call. Small. Dropping one **re-bills that
    call**, unconditionally.
``content``
    The content-addressed blobs (falaw#14). This is where the gigabytes are.
    Dropping one re-bills every call whose asset URL has since expired — fal
    deletes expired files permanently, so the blob was the last copy.
``assets``
    :func:`falaw.materialize_asset` output — a *copy* of a blob, not a hard
    link (deliberately; see :func:`falaw.content.write_blob_to_file`). It
    doubles the on-disk cost of every materialized asset and is the **cheapest**
    thing to reclaim: while the blob survives, re-materializing is a local copy
    and costs nothing.
``url_index``
    ``url -> content hash`` hints. Tiny — and **not** droppable freely, despite
    the name. :func:`falaw.content.content_ref_for_url` reaches a blob *only*
    through :func:`falaw.content.remembered_ref`, so deleting this index orphans
    the entire ``content`` area: every entry whose fal URL has since expired
    re-**renders**, and the bytes it needed are still on disk, unreachable.
    Nothing here prunes it.
``scenes``
    Saved Scene IR. Not media and not a cache — it is *authored input*, so
    losing one is lost work rather than a re-render. Nothing here prunes it.
``other``
    Whatever the named areas do not claim: a crashed write's ``.part``
    leftover, or a directory a future falaw feature adds without telling this
    module. Present so that the totals cannot silently under-report.

Examples
--------

What is actually on disk, broken down by area (``+SKIP``\\ ed because it reads
the caller's real cache, which on the production box is a multi-gigabyte walk —
:mod:`tests.test_prune` pins the same behaviour against a throwaway one):

>>> usage = cache_usage()                            # doctest: +SKIP
>>> sorted(a.name for a in usage.areas)              # doctest: +SKIP
['assets', 'content', 'manifests', 'other', 'scenes', 'url_index']

A prune is a dry run unless you say otherwise, and refuses to run unbounded
(this one raises before touching the disk, so it is safe to execute):

>>> prune_content()
Traceback (most recent call last):
    ...
ValueError: prune_content needs a bound: pass older_than= and/or max_bytes=...
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Iterator, Optional, Sequence, Union

from .cache import ASSETS_DIRNAME, _cache_dir
from .content import CONTENT_STORE_DIRNAME, URL_INDEX_DIRNAME, remembered_ref
from .upload import UPLOAD_INDEX_DIRNAME


__all__ = [
    "AreaUsage",
    "CacheUsage",
    "PruneCandidate",
    "PruneReport",
    "cache_usage",
    "prune_assets",
    "prune_content",
    "prune_manifests",
]


MANIFESTS_AREA = "manifests"
CONTENT_AREA = "content"
ASSETS_AREA = "assets"
URL_INDEX_AREA = "url_index"
SCENES_AREA = "scenes"
UPLOADS_AREA = "uploads"
OTHER_AREA = "other"

AREA_NAMES = (
    MANIFESTS_AREA,
    CONTENT_AREA,
    ASSETS_AREA,
    URL_INDEX_AREA,
    SCENES_AREA,
    UPLOADS_AREA,
    OTHER_AREA,
)
"""Every area :func:`cache_usage` reports."""

SCENES_DIRNAME = "scenes"
"""Saved Scene IR, written by :func:`falaw.operations.render.save_scene`."""

AREA_DIRNAMES = (
    CONTENT_STORE_DIRNAME,
    ASSETS_DIRNAME,
    URL_INDEX_DIRNAME,
    SCENES_DIRNAME,
    UPLOAD_INDEX_DIRNAME,
)
"""Directory names at the cache root owned by a named area.

The cache-entry shards are two hex characters (``_entry_dir`` shards on
``key[:2]`` of a SHA-256 hexdigest), and no name here is two characters long,
so the shard layout and the area layout cannot collide.
"""

MANIFEST_FILENAME = "manifest.json"
"""The one filename a cache entry directory is guaranteed to contain."""

PART_SUFFIX = ".part"
"""Suffix of an in-flight write (``cache_put``, ``write_blob_to_file``).

Never a prune candidate: the file is mid-``os.replace`` and deleting it breaks
the writer that owns it.
"""

CONTENT_HASH_LENGTH = 64
"""Hex characters in a SHA-256 digest — how an asset filename's hash is found."""

Age = Union[float, int, timedelta]
"""An age bound: seconds, or a :class:`~datetime.timedelta`."""


# --- usage ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AreaUsage:
    """Disk usage of one cache area.

    ``entries`` counts the area's own unit — cache entries for ``manifests``,
    blobs for ``content``, files for ``assets`` and ``url_index`` — not files
    on disk, which is why it is reported next to ``bytes`` rather than derived
    from it.

    ``path`` is ``None`` when the area has no directory of its own. That is the
    case for ``manifests`` (scattered across two-character shard directories at
    the cache root) and for ``other``. It is deliberately not the cache root:
    a caller reaching for ``rmtree(usage.area(...).path)`` would then destroy
    the content store along with it.
    """

    name: str
    path: Optional[str]
    entries: int
    bytes: int

    @property
    def megabytes(self) -> float:
        return round(self.bytes / 1_000_000, 2)


@dataclass(frozen=True, slots=True)
class CacheUsage:
    """Where the falaw cache's disk is going, by area.

    The whole point of the breakdown: ``size_bytes`` alone cannot tell you
    whether you are looking at gigabytes of irreplaceable blobs or gigabytes of
    ``assets/`` copies that cost nothing to regenerate.
    """

    root: str
    areas: tuple[AreaUsage, ...]

    @property
    def total_bytes(self) -> int:
        """Every byte under the cache root.

        Equal to a full walk of the root, because ``other`` absorbs whatever the
        named areas do not claim. That identity is the point: a capacity report
        whose total is "the sum of the areas I thought to enumerate" silently
        under-reports the moment falaw grows a directory nobody added here, and
        under-reporting is the one direction a capacity tool cannot afford.
        """
        return sum(a.bytes for a in self.areas)

    @property
    def total_megabytes(self) -> float:
        return round(self.total_bytes / 1_000_000, 2)

    def area(self, name: str) -> AreaUsage:
        """The :class:`AreaUsage` named ``name``.

        Raises:
            KeyError: no such area. The valid names are :data:`AREA_NAMES`.
        """
        for a in self.areas:
            if a.name == name:
                return a
        raise KeyError(f"no cache area named {name!r}; expected one of {AREA_NAMES}")

    def summary(self) -> str:
        """One human-readable line per area, largest first."""
        lines = [f"falaw cache at {self.root}: {self.total_megabytes} MB total"]
        for a in sorted(self.areas, key=lambda a: a.bytes, reverse=True):
            lines.append(f"  {a.name:<10} {a.megabytes:>10} MB  ({a.entries} entries)")
        return "\n".join(lines)


def cache_usage() -> CacheUsage:
    """Disk usage of the falaw cache, broken down by area.

    The structured form behind :func:`falaw.cache_stats`. Read the module
    docstring for what each area costs to reclaim.
    """
    root = _cache_dir()
    named = (
        _manifests_usage(root),
        _content_usage(root),
        _assets_usage(root),
        _url_index_usage(root),
        _scenes_usage(root),
        _uploads_usage(root),
    )
    return CacheUsage(root=root, areas=named + (_other_usage(root, named),))


def _other_usage(root: str, named: Sequence[AreaUsage]) -> AreaUsage:
    """Everything under the cache root the named areas did not claim.

    Not a rounding error — it is the honesty valve. It catches a crashed
    ``cache_put``'s ``.part`` leftover, any file in an entry directory that is
    not ``manifest.json``, and any directory a future falaw feature adds without
    telling this module. Those bytes are real and occupy the same volume; a
    breakdown that quietly omitted them would let the disk fill while the report
    said everything was accounted for.

    Computed by walking the root and skipping what the named areas own, rather
    than by subtracting their totals — subtraction would hide a double-count as
    a plausible-looking number instead of surfacing it.

    Nothing prunes ``other``, deliberately: falaw does not know what it is.
    """
    owned_dirs = {os.path.join(root, d) for d in AREA_DIRNAMES}
    files = 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath in owned_dirs:
            dirnames[:] = []  # an owned area: do not descend
            continue
        for name in filenames:
            if name == MANIFEST_FILENAME:
                continue  # claimed by the `manifests` area
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
            files += 1
    return AreaUsage(name=OTHER_AREA, path=None, entries=files, bytes=total)


def _dir_bytes(path: str) -> tuple[int, int]:
    """``(file_count, total_bytes)`` under ``path``; ``(0, 0)`` when absent."""
    files = 0
    total = 0
    for dirpath, _dirs, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:  # vanished under us — a prune elsewhere, or a temp file
                continue
            files += 1
    return files, total


def _manifests_usage(root: str) -> AreaUsage:
    entries = 0
    total = 0
    for path in _iter_manifest_paths(root):
        entries += 1
        try:
            total += os.path.getsize(path)
        except OSError:
            continue
    # `path=None`: manifests are scattered across shard directories at the
    # cache root, and reporting the root here would invite an `rmtree` that
    # takes the content store with it.
    return AreaUsage(name=MANIFESTS_AREA, path=None, entries=entries, bytes=total)


def _content_usage(root: str) -> AreaUsage:
    path = os.path.join(root, CONTENT_STORE_DIRNAME)
    # Count *blobs*, not files: `from_directory` also lays down a `catalog/`,
    # which falaw never writes but which would otherwise inflate the count.
    blobs_dir = os.path.join(path, "blobs")
    entries, _ = _dir_bytes(blobs_dir)
    _, total = _dir_bytes(path)
    return AreaUsage(name=CONTENT_AREA, path=path, entries=entries, bytes=total)


def _assets_usage(root: str) -> AreaUsage:
    """Usage of ``assets/``, counted over exactly what :func:`prune_assets` can reach.

    Both use the same flat listing and both skip ``.part`` files, so a
    ``max_bytes`` budget over this area can actually converge. When they
    disagreed, ``prune_assets(max_bytes=N)`` could report bytes it had no way to
    delete and loop forever without reaching the budget.
    """
    path = os.path.join(root, ASSETS_DIRNAME)
    candidates = _asset_candidates(root)
    return AreaUsage(
        name=ASSETS_AREA,
        path=path,
        entries=len(candidates),
        bytes=sum(c.bytes for c in candidates),
    )


def _url_index_usage(root: str) -> AreaUsage:
    path = os.path.join(root, URL_INDEX_DIRNAME)
    entries, total = _dir_bytes(path)
    return AreaUsage(name=URL_INDEX_AREA, path=path, entries=entries, bytes=total)


def _uploads_usage(root: str) -> AreaUsage:
    path = os.path.join(root, UPLOAD_INDEX_DIRNAME)
    entries, total = _dir_bytes(path)
    return AreaUsage(name=UPLOADS_AREA, path=path, entries=entries, bytes=total)


def _scenes_usage(root: str) -> AreaUsage:
    """Usage of ``scenes/`` — saved Scene IR, not media.

    Its own area because it is falaw's, is written by a different subsystem
    (``save_scene``), and has economics unlike anything else here: a Scene is
    the *authored* input, so losing one is not a re-render, it is lost work.
    Nothing here prunes it.
    """
    path = os.path.join(root, SCENES_DIRNAME)
    entries, total = _dir_bytes(path)
    return AreaUsage(name=SCENES_AREA, path=path, entries=entries, bytes=total)


def _iter_manifest_paths(root: Optional[str] = None) -> Iterator[str]:
    """Every ``manifest.json`` in the cache, skipping the three named areas.

    Cache entries live at ``<root>/<2-hex>/<key>/manifest.json``. The other
    areas are named directories (``content``, ``assets``, ``url_index``), none
    of which is two characters long, so the shard layout and the area layout
    cannot collide.
    """
    root = _cache_dir() if root is None else root
    # Every area directory, from the one constant — not a hand-listed subset.
    # `scenes/` was missing from an earlier hand-listed copy, which made a file
    # named `manifest.json` under it look like a prunable cache entry.
    try:
        shards = os.listdir(root)
    except OSError:
        return
    for shard in shards:
        if shard in AREA_DIRNAMES:
            continue
        shard_dir = os.path.join(root, shard)
        if not os.path.isdir(shard_dir):
            continue
        for dirpath, _dirs, filenames in os.walk(shard_dir):
            if MANIFEST_FILENAME in filenames:
                yield os.path.join(dirpath, MANIFEST_FILENAME)


# --- prune reports ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PruneCandidate:
    """One thing a prune would delete (or did).

    ``last_modified`` is ``None`` when the age could not be determined — a
    non-filesystem blob backend, or a manifest too corrupt to read. Such a
    candidate is never selected by ``older_than`` (an unprovable age is not
    evidence of staleness) and is evicted last under ``max_bytes``.
    """

    key: str
    path: str
    bytes: int
    last_modified: Optional[float] = None


@dataclass(frozen=True, slots=True)
class PruneReport:
    """What a prune removed, or — with ``dry_run=True`` — would remove.

    ``rebillable_entries`` is the number this exists for: cache entries that
    will **cost money again** because of this prune. Its meaning is exact per
    area, and each is a different claim:

    - ``manifests`` — every dropped entry re-bills, so it equals the candidate
      count.
    - ``content`` — entries whose recorded response names an asset that resolves
      (through the ``url -> hash`` index) to a blob being dropped. Those become
      *unmaterializable* from cache; they re-download if fal still serves the
      URL and re-render if it does not, and falaw cannot tell which from here.
      It mirrors the predicate :func:`falaw.plan.execute` applies to a hit from
      the **built-in** converter. It is therefore an *upper* bound, not an exact
      population: with a custom ``artifact_converter=`` the entry is never
      dropped (it returns a broken artifact instead), and with
      ``fetch_bytes=False`` dropping the blob changes nothing. Both errors are
      overcounts — the safe direction for a number you read before spending.
    - ``assets`` — only the copies whose blob is *also* gone. While the blob
      survives, re-materializing is a local copy and costs nothing.

    ``unreferenced_candidates`` is the other half of the story, and only
    ``content`` populates it: blobs that **no manifest points at**. falaw cannot
    tell whether such a blob is garbage or the last copy of something
    irreplaceable — :func:`falaw.materialize_asset` puts reference images and
    locally-rendered ``file://`` media in the same store, and those never had a
    fal response behind them. Counting them as ``rebillable`` would be wrong
    (no cache entry re-bills), but reporting nothing would tell an operator the
    prune is free when it may be destroying the only copy of a reference image.
    """

    area: str
    dry_run: bool
    candidates: tuple[PruneCandidate, ...] = ()
    deleted: tuple[PruneCandidate, ...] = ()
    kept_entries: int = 0
    kept_bytes: int = 0
    rebillable_entries: int = 0
    unreferenced_candidates: int = 0
    errors: tuple[str, ...] = field(default=())

    @property
    def freed_bytes(self) -> int:
        """Bytes actually freed — or, under ``dry_run``, that would be freed.

        Sums ``deleted``, **not** ``candidates``. A deletion that failed (a
        read-only volume, a permission error) leaves its bytes on disk, and a
        capacity tool that reports them as reclaimed tells an operator staring
        at a full disk that the problem is solved when it is not.
        """
        return sum(c.bytes for c in self.deleted)

    @property
    def freed_megabytes(self) -> float:
        return round(self.freed_bytes / 1_000_000, 2)

    def summary(self) -> str:
        """A human-readable line, phrased in the tense the run actually was."""
        verb = "would free" if self.dry_run else "freed"
        parts = [
            f"{self.area}: {verb} {self.freed_megabytes} MB "
            f"across {len(self.deleted)} entries "
            f"({self.kept_entries} kept, {round(self.kept_bytes / 1_000_000, 2)} MB)"
        ]
        if self.rebillable_entries:
            tense = "would become" if self.dry_run else "became"
            parts.append(
                f"  WARNING: up to {self.rebillable_entries} cache "
                f"{'entry' if self.rebillable_entries == 1 else 'entries'} "
                f"{tense} re-billable — re-running them costs money again"
            )
        if self.unreferenced_candidates:
            parts.append(
                f"  WARNING: {self.unreferenced_candidates} blob(s) have no cache "
                "entry behind them — falaw cannot tell garbage from the last "
                "copy of a materialized reference asset"
            )
        if self.errors:
            failed = len(self.candidates) - len(self.deleted)
            parts.append(
                f"  {failed} deletion(s) FAILED and their bytes remain: "
                f"{self.errors[0]}"
            )
        return "\n".join(parts)


# --- selection --------------------------------------------------------------


def _as_seconds(older_than: Age) -> float:
    if isinstance(older_than, timedelta):
        return older_than.total_seconds()
    return float(older_than)


def _require_a_bound(func_name: str, older_than, max_bytes) -> None:
    """Refuse an unbounded prune, and refuse a bound that is a bug.

    Neither reading of a missing bound is safe to guess: "delete everything"
    would silently make the whole cache re-billable, and "delete nothing" would
    make a command the caller believes reclaimed space a no-op.

    A **non-positive** ``older_than`` is refused for a different reason: it is
    almost never typed by hand. It arrives as ``days * DAY`` with ``days`` read
    from a config that defaulted to 0, and it means "older than now" — a total
    wipe of the area, from a caller who asked for an age filter. A caller who
    genuinely wants everything gone says ``max_bytes=0``, which is unambiguous.
    """
    if older_than is None and max_bytes is None:
        raise ValueError(
            f"{func_name} needs a bound: pass older_than= and/or max_bytes=. "
            "Refusing to guess whether an unbounded call means 'everything' "
            "or 'nothing' — one of those silently re-bills your whole cache."
        )
    if older_than is not None and _as_seconds(older_than) <= 0:
        raise ValueError(
            f"{func_name}: older_than must be positive, got {older_than!r}. "
            "'Older than now' selects the entire area, which is almost always "
            "a computed-zero bug rather than an intent. Pass max_bytes=0 if you "
            "really mean 'drop everything'."
        )
    if max_bytes is not None and max_bytes < 0:
        raise ValueError(f"{func_name}: max_bytes must be >= 0, got {max_bytes!r}.")


def _select(
    candidates: Sequence[PruneCandidate],
    *,
    older_than: Optional[Age],
    max_bytes: Optional[int],
    now: float,
) -> tuple[list[PruneCandidate], list[PruneCandidate]]:
    """Split ``candidates`` into ``(to_delete, to_keep)``.

    Age is the file's mtime — when falaw last **wrote** those bytes, not when
    it last read them. That is a deliberate limitation, not an oversight: POSIX
    atime is unreliable under ``relatime``/``noatime``, and falaw's hottest read
    path (:func:`falaw.materialize_asset` circle 1) never opens the blob at all,
    so a true LRU would need write-on-read bookkeeping on the path that exists
    to avoid I/O. Age-ordered eviction is what this is; it is not LRU and the
    docstrings do not claim to be.
    """
    doomed: list[PruneCandidate] = []
    survivors = list(candidates)

    if older_than is not None:
        cutoff = now - _as_seconds(older_than)
        aged = [
            c
            for c in survivors
            if c.last_modified is not None and c.last_modified < cutoff
        ]
        doomed.extend(aged)
        aged_ids = {id(c) for c in aged}
        survivors = [c for c in survivors if id(c) not in aged_ids]

    if max_bytes is not None:
        # Evict oldest-first until what remains fits — the minimum number of
        # oldest items that reaches the budget.
        #
        # NOT a greedy keep-what-fits scan over a newest-first list, which is
        # what an earlier cut of this did: that skips an item too big to fit and
        # keeps scanning, so it deletes *newer, larger* entries while retaining
        # older, smaller ones behind them. On a media cache (an 8 MB clip beside
        # 200 KB thumbnails) that is the normal case, not the corner one, and
        # every large recent blob it drops is a candidate re-bill of the most
        # expensive render in the project.
        eviction_order = sorted(survivors, key=_eviction_key)
        remaining = sum(c.bytes for c in survivors)
        cut = 0
        while remaining > max_bytes and cut < len(eviction_order):
            remaining -= eviction_order[cut].bytes
            cut += 1
        doomed.extend(eviction_order[:cut])
        survivors = eviction_order[cut:]

    return doomed, survivors


def _eviction_key(candidate: PruneCandidate):
    """Sort key placing the first-to-evict first.

    Oldest first; unknown age **last**, so an unprovable age is evicted only
    when dropping everything datable was not enough. ``key`` breaks ties so two
    candidates of identical age evict in the same order on every machine —
    otherwise the choice falls through to filesystem listing order.
    """
    return (
        candidate.last_modified is None,
        candidate.last_modified if candidate.last_modified is not None else 0.0,
        candidate.key,
    )


def _delete(
    remove, candidates: Sequence[PruneCandidate]
) -> tuple[tuple[PruneCandidate, ...], tuple[str, ...]]:
    """Run ``remove`` over each candidate; return ``(deleted, errors)``.

    A prune that aborts halfway leaves the caller with neither the disk nor a
    report, so a failed deletion is recorded and the sweep continues. Returning
    the *deleted* set separately is what keeps ``freed_bytes`` honest — see
    :attr:`PruneReport.freed_bytes`.
    """
    deleted = []
    errors = []
    for c in candidates:
        try:
            remove(c)
        except Exception as e:  # noqa: BLE001 — one bad file must not abort the sweep
            errors.append(f"{c.key}: {type(e).__name__}: {e}")
        else:
            deleted.append(c)
    return tuple(deleted), tuple(errors)


# --- content ----------------------------------------------------------------


def _blob_candidates(store) -> list[PruneCandidate]:
    # `iter_blobs`, not `iter(store.blobs)`: on a filesystem store the raw
    # `dol.Files` listing follows symlinked directories, so it can yield files
    # outside the blob root (falaw#66, lacing#55). Listed up front so the
    # later deletes do not mutate what is being iterated.
    out = []
    for content_hash in list(store.iter_blobs()):
        path = store.blob_path(content_hash)
        if path is not None:
            try:
                st = os.stat(path)
            except OSError:
                continue
            out.append(
                PruneCandidate(
                    key=content_hash,
                    path=str(path),
                    bytes=st.st_size,
                    last_modified=st.st_mtime,
                )
            )
        else:
            # Opaque backend (in-memory, object store): size is knowable, age
            # is not. `_select` keeps unknown-age blobs unless space forces it.
            try:
                data = store.get_blob(content_hash)
            except Exception:  # noqa: BLE001 — an unreadable blob is not prunable data
                continue
            if data is None:
                continue
            size = len(data)
            out.append(
                PruneCandidate(
                    key=content_hash, path="", bytes=size, last_modified=None
                )
            )
    return out


def _reference_counts(doomed_hashes: set[str], root: str) -> tuple[int, int]:
    """``(rebillable_entries, unreferenced_candidates)`` for a content prune.

    Walks manifests, extracts each response's asset URL exactly as
    :func:`falaw.plan.execute` does, and maps it through the ``url -> hash``
    hint index. An entry that fails any step is skipped: it is already
    unmaterializable, so a prune is not what breaks it.

    The second number is the one an earlier cut got wrong by not computing it.
    A blob **no manifest points at** is not rebillable — no cache entry
    re-bills — but it is not therefore free: :func:`falaw.materialize_asset`
    puts reference images and locally-rendered ``file://`` media in the same
    store, and those never had a fal response behind them. Reporting only
    ``rebillable`` told an operator such a prune was free while it destroyed
    the last copy.
    """
    if not doomed_hashes:
        return 0, 0
    from .plan import extract_first_url

    rebillable = 0
    referenced: set[str] = set()
    for path in _iter_manifest_paths(root):
        try:
            with open(path) as f:
                manifest = json.load(f)
        except Exception:  # noqa: BLE001 — a corrupt manifest is already a miss
            continue
        url = extract_first_url(manifest.get("raw") or {})
        if not url:
            continue
        ref = remembered_ref(url)
        if ref is not None and ref.content_hash in doomed_hashes:
            rebillable += 1
            referenced.add(ref.content_hash)
    return rebillable, len(doomed_hashes - referenced)


def prune_content(
    *,
    older_than: Optional[Age] = None,
    max_bytes: Optional[int] = None,
    dry_run: bool = True,
    store=None,
) -> PruneReport:
    """Reclaim content-addressed blobs — the gigabytes (falaw#22).

    This is the **expensive** prune. A blob is the last copy of an asset once
    fal has expired its URL ("expired files are permanently deleted and cannot
    be recovered"), so dropping one can turn a free cache hit into a re-rendered
    clip. The report says how many entries that applies to *before* you commit;
    read ``rebillable_entries``.

    Args:
        older_than: drop blobs last written more than this ago — seconds, or a
            :class:`~datetime.timedelta`.
        max_bytes: drop oldest-first until the area fits in this budget.
        dry_run: report without deleting. Default, deliberately.
        store: injected :class:`lacing.ArtifactStore`; defaults to
            :func:`falaw.content.default_content_store`, whose deletes remove
            the file. An injected store keeps its own backend's delete policy:
            a stock ``ArtifactStore.from_directory`` store moves each blob to
            the OS trash, which frees no space on that volume even though the
            report counts the bytes as freed.

    Blobs are listed and deleted through lacing's contained
    ``iter_blobs``/``delete_blob`` (falaw#66): nothing outside the blob root is
    listed or removed, and an in-root symlink is unlinked, never its target.

    Returns:
        PruneReport: with ``area="content"``.

    Raises:
        ValueError: neither bound was given — see :func:`_require_a_bound`.

    Both bounds may be combined; a blob selected by either is dropped.

    >>> report = prune_content(older_than=timedelta(days=90))  # doctest: +SKIP
    >>> report.dry_run                                         # doctest: +SKIP
    True
    """
    _require_a_bound("prune_content", older_than, max_bytes)
    from .content import default_content_store

    store = default_content_store() if store is None else store
    root = _cache_dir()

    doomed, survivors = _select(
        _blob_candidates(store),
        older_than=older_than,
        max_bytes=max_bytes,
        now=time.time(),
    )
    rebillable, unreferenced = _reference_counts({c.key for c in doomed}, root)

    deleted: tuple[PruneCandidate, ...] = tuple(doomed)
    errors: tuple[str, ...] = ()
    if not dry_run:
        deleted, errors = _delete(lambda c: store.delete_blob(c.key), doomed)

    return PruneReport(
        area=CONTENT_AREA,
        dry_run=dry_run,
        candidates=tuple(doomed),
        deleted=deleted,
        kept_entries=len(survivors),
        kept_bytes=sum(c.bytes for c in survivors),
        rebillable_entries=rebillable,
        unreferenced_candidates=unreferenced,
        errors=errors,
    )


# --- manifests --------------------------------------------------------------


def _manifest_candidates(root: str) -> list[PruneCandidate]:
    out = []
    for path in _iter_manifest_paths(root):
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        # `stored_at` is the truth (the manifest records when falaw wrote it);
        # mtime is the fallback for an entry too corrupt to parse.
        stored_at: Optional[float] = None
        try:
            with open(path) as f:
                stored_at = float(json.load(f).get("stored_at"))
        except Exception:  # noqa: BLE001 — fall back to the filesystem's opinion
            try:
                stored_at = os.path.getmtime(path)
            except OSError:
                stored_at = None
        out.append(
            PruneCandidate(
                key=os.path.basename(os.path.dirname(path)),
                path=path,
                bytes=size,
                last_modified=stored_at,
            )
        )
    return out


def prune_manifests(
    *,
    older_than: Optional[Age] = None,
    max_bytes: Optional[int] = None,
    dry_run: bool = True,
) -> PruneReport:
    """Reclaim cache entries — the fal responses themselves (falaw#22).

    Manifests are kilobytes, so this is rarely where the disk is; it is here
    because a stale *entry* is its own problem — it pins a model version and a
    price you may no longer want served from cache.

    Unlike :func:`prune_content`, the cost is unconditional: every dropped
    entry re-bills its call on the next run, so ``rebillable_entries`` always
    equals the candidate count.

    Args:
        older_than: drop entries stored more than this ago — seconds, or a
            :class:`~datetime.timedelta`. Read from the manifest's own
            ``stored_at``, falling back to file mtime.
        max_bytes: drop oldest-first until the area fits in this budget.
        dry_run: report without deleting. Default, deliberately.

    Returns:
        PruneReport: with ``area="manifests"``.

    Raises:
        ValueError: neither bound was given.

    Only the manifest is removed; blobs are shared by content hash across
    entries and are never dropped from here — the same rule
    :func:`falaw.drop_cache_entry` follows.
    """
    _require_a_bound("prune_manifests", older_than, max_bytes)
    root = _cache_dir()
    doomed, survivors = _select(
        _manifest_candidates(root),
        older_than=older_than,
        max_bytes=max_bytes,
        now=time.time(),
    )
    deleted: tuple[PruneCandidate, ...] = tuple(doomed)
    errors: tuple[str, ...] = ()
    if not dry_run:
        deleted, errors = _delete(lambda c: os.remove(c.path), doomed)
    return PruneReport(
        area=MANIFESTS_AREA,
        dry_run=dry_run,
        candidates=tuple(doomed),
        deleted=deleted,
        kept_entries=len(survivors),
        kept_bytes=sum(c.bytes for c in survivors),
        # Every entry that actually goes away re-bills its call. Keyed on
        # `deleted`, not `candidates`: an entry whose deletion failed is still
        # in the cache and still serves its hit.
        rebillable_entries=len(deleted),
        errors=errors,
    )


# --- assets -----------------------------------------------------------------


def _content_hash_in_asset_name(filename: str) -> Optional[str]:
    """The content hash embedded in a :func:`falaw.materialize_asset` filename.

    The layout is ``{key_hint-}{content_hash}{ext}``, so the hash is the last
    64 hex characters of the stem. ``None`` when the name does not fit — a file
    falaw did not write, which is reason enough not to reason about it.
    """
    stem = os.path.splitext(filename)[0]
    if len(stem) < CONTENT_HASH_LENGTH:
        return None
    tail = stem[-CONTENT_HASH_LENGTH:]
    try:
        int(tail, 16)
    except ValueError:
        return None
    return tail


def _asset_candidates(root: str) -> list[PruneCandidate]:
    """Materialized asset copies, excluding writes still in flight.

    ``.part`` files are skipped, and that is a correctness requirement rather
    than tidiness: :func:`falaw.content.write_blob_to_file` writes
    ``{path}.{uuid}.part`` **inside** ``assets/`` and then ``os.replace``\\ s it
    into position, so a prune racing a live ``materialize_asset`` — entirely
    reachable under ``execute_plan(concurrency=N)`` — would delete the temp file
    out from under it and the racing rename would raise ``FileNotFoundError``.
    They would also be counted as orphaned copies, since a ``.part`` name
    carries no content hash.
    """
    path = os.path.join(root, ASSETS_DIRNAME)
    out = []
    try:
        names = os.listdir(path)
    except OSError:
        return out
    for name in names:
        if name.endswith(PART_SUFFIX):
            continue
        full = os.path.join(path, name)
        try:
            st = os.stat(full)
        except OSError:
            continue
        if not os.path.isfile(full):
            continue
        out.append(
            PruneCandidate(
                key=name, path=full, bytes=st.st_size, last_modified=st.st_mtime
            )
        )
    return out


def prune_assets(
    *,
    older_than: Optional[Age] = None,
    max_bytes: Optional[int] = None,
    dry_run: bool = True,
    store=None,
) -> PruneReport:
    """Reclaim materialized asset copies — the cheapest disk in the cache (falaw#22).

    ``assets/`` holds a **copy** of each blob rather than a hard link, which is
    deliberate (:func:`falaw.content.write_blob_to_file` explains why a link
    would let a consumer corrupt the content store) but doubles the on-disk cost
    of every materialized asset. That makes this the prune to reach for first:
    while a blob survives, re-materializing its asset is a local copy and costs
    nothing, so ``rebillable_entries`` counts only the copies whose blob is
    *also* gone.

    Args:
        older_than: drop copies last written more than this ago — seconds, or a
            :class:`~datetime.timedelta`.
        max_bytes: drop oldest-first until the area fits in this budget.
        dry_run: report without deleting. Default, deliberately.
        store: injected :class:`lacing.ArtifactStore`, used only to ask whether
            each dropped copy still has a blob behind it; defaults to
            :func:`falaw.content.default_content_store`.

    Returns:
        PruneReport: with ``area="assets"``.

    Raises:
        ValueError: neither bound was given.
    """
    _require_a_bound("prune_assets", older_than, max_bytes)
    from .content import default_content_store

    store = default_content_store() if store is None else store
    root = _cache_dir()
    doomed, survivors = _select(
        _asset_candidates(root),
        older_than=older_than,
        max_bytes=max_bytes,
        now=time.time(),
    )
    orphaned = 0
    for c in doomed:
        content_hash = _content_hash_in_asset_name(c.key)
        if content_hash is None or not store.has_blob(content_hash):
            orphaned += 1

    deleted: tuple[PruneCandidate, ...] = tuple(doomed)
    errors: tuple[str, ...] = ()
    if not dry_run:
        deleted, errors = _delete(lambda c: os.remove(c.path), doomed)

    return PruneReport(
        area=ASSETS_AREA,
        dry_run=dry_run,
        candidates=tuple(doomed),
        deleted=deleted,
        kept_entries=len(survivors),
        kept_bytes=sum(c.bytes for c in survivors),
        rebillable_entries=orphaned,
        errors=errors,
    )
