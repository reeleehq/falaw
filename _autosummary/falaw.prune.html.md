# falaw.prune

Capacity management for the falaw cache: see what is on disk, and reclaim it.

Before thorwhalen/falaw#14 the cache held kilobyte JSON manifests. It now
content-addresses every media result, so it also holds the **bytes** of every
generated image, clip and audio track. On any machine that has rendered a real
project that is gigabytes, and on the production box (a 40 GB volume) it is a
capacity question rather than a cosmetic one.

Nothing here runs automatically, and that is the design rather than an omission.
**Deleting a blob is a spending decision**: [`falaw.plan.execute()`](falaw.plan.html.md#falaw.plan.execute) treats a
cache entry it cannot turn back into bytes as a *miss* and re-executes it, so
disk reclaimed today is re-billed the next time that beat renders. Every prune
is therefore `dry_run=True` by default and returns a [`PruneReport`](#falaw.prune.PruneReport)
that says — before anything is removed — how many cache entries the prune would
put back on the invoice.

The cache has six areas, with very different economics — and only one of them
is genuinely cheap to reclaim:

`manifests`
: The fal responses, keyed by call. Small. Dropping one \*\*re-bills that
  call\*\*, unconditionally.

`content`
: The content-addressed blobs (falaw#14). This is where the gigabytes are.
  Dropping one re-bills every call whose asset URL has since expired — fal
  deletes expired files permanently, so the blob was the last copy.

`assets`
: [`falaw.materialize_asset()`](falaw.html.md#falaw.materialize_asset) output — a *copy* of a blob, not a hard
  link (deliberately; see [`falaw.content.write_blob_to_file()`](falaw.content.html.md#falaw.content.write_blob_to_file)). It
  doubles the on-disk cost of every materialized asset and is the **cheapest**
  thing to reclaim: while the blob survives, re-materializing is a local copy
  and costs nothing.

`url_index`
: `url -> content hash` hints. Tiny — and **not** droppable freely, despite
  the name. [`falaw.content.content_ref_for_url()`](falaw.content.html.md#falaw.content.content_ref_for_url) reaches a blob *only*
  through [`falaw.content.remembered_ref()`](falaw.content.html.md#falaw.content.remembered_ref), so deleting this index orphans
  the entire `content` area: every entry whose fal URL has since expired
  re-**renders**, and the bytes it needed are still on disk, unreachable.
  Nothing here prunes it.

`scenes`
: Saved Scene IR. Not media and not a cache — it is *authored input*, so
  losing one is lost work rather than a re-render. Nothing here prunes it.

`other`
: Whatever the named areas do not claim: a crashed write’s `.part`
  leftover, or a directory a future falaw feature adds without telling this
  module. Present so that the totals cannot silently under-report.

### Examples

What is actually on disk, broken down by area (`+SKIP`ed because it reads
the caller’s real cache, which on the production box is a multi-gigabyte walk —
`tests.test_prune` pins the same behaviour against a throwaway one):

```pycon
>>> usage = cache_usage()
>>> sorted(a.name for a in usage.areas)
['assets', 'content', 'manifests', 'other', 'scenes', 'url_index']
```

A prune is a dry run unless you say otherwise, and refuses to run unbounded
(this one raises before touching the disk, so it is safe to execute):

```pycon
>>> prune_content()
Traceback (most recent call last):
    ...
ValueError: prune_content needs a bound: pass older_than= and/or max_bytes=...
```

### Functions

| [`cache_usage`](#falaw.prune.cache_usage)()                                     | Disk usage of the falaw cache, broken down by area.                            |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| [`prune_assets`](#falaw.prune.prune_assets)(\*[, older_than, max_bytes, ...])    | Reclaim materialized asset copies — the cheapest disk in the cache (falaw#22). |
| [`prune_content`](#falaw.prune.prune_content)(\*[, older_than, max_bytes, ...])   | Reclaim content-addressed blobs — the gigabytes (falaw#22).                    |
| [`prune_manifests`](#falaw.prune.prune_manifests)(\*[, older_than, max_bytes, ...]) | Reclaim cache entries — the fal responses themselves (falaw#22).               |

### Classes

| [`AreaUsage`](#falaw.prune.AreaUsage)(name, path, entries, bytes)             | Disk usage of one cache area.                                  |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------|
| [`CacheUsage`](#falaw.prune.CacheUsage)(root, areas)                           | Where the falaw cache's disk is going, by area.                |
| [`PruneCandidate`](#falaw.prune.PruneCandidate)(key, path, bytes[, last_modified]) | One thing a prune would delete (or did).                       |
| [`PruneReport`](#falaw.prune.PruneReport)(area, dry_run[, candidates, ...])     | What a prune removed, or — with `dry_run=True` — would remove. |

### *class* falaw.prune.AreaUsage(name, path, entries, bytes)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Disk usage of one cache area.

`entries` counts the area’s own unit — cache entries for `manifests`,
blobs for `content`, files for `assets` and `url_index` — not files
on disk, which is why it is reported next to `bytes` rather than derived
from it.

`path` is `None` when the area has no directory of its own. That is the
case for `manifests` (scattered across two-character shard directories at
the cache root) and for `other`. It is deliberately not the cache root:
a caller reaching for `rmtree(usage.area(...).path)` would then destroy
the content store along with it.

### *class* falaw.prune.CacheUsage(root, areas)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Where the falaw cache’s disk is going, by area.

The whole point of the breakdown: `size_bytes` alone cannot tell you
whether you are looking at gigabytes of irreplaceable blobs or gigabytes of
`assets/` copies that cost nothing to regenerate.

#### area(name)

The [`AreaUsage`](#falaw.prune.AreaUsage) named `name`.

* **Raises:**
  [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – no such area. The valid names are `AREA_NAMES`.
* **Return type:**
  [`AreaUsage`](#falaw.prune.AreaUsage)

#### summary()

One human-readable line per area, largest first.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### *property* total_bytes *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Every byte under the cache root.

Equal to a full walk of the root, because `other` absorbs whatever the
named areas do not claim. That identity is the point: a capacity report
whose total is “the sum of the areas I thought to enumerate” silently
under-reports the moment falaw grows a directory nobody added here, and
under-reporting is the one direction a capacity tool cannot afford.

### *class* falaw.prune.PruneCandidate(key, path, bytes, last_modified=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One thing a prune would delete (or did).

`last_modified` is `None` when the age could not be determined — a
non-filesystem blob backend, or a manifest too corrupt to read. Such a
candidate is never selected by `older_than` (an unprovable age is not
evidence of staleness) and is evicted last under `max_bytes`.

### *class* falaw.prune.PruneReport(area, dry_run, candidates=(), deleted=(), kept_entries=0, kept_bytes=0, rebillable_entries=0, unreferenced_candidates=0, errors=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a prune removed, or — with `dry_run=True` — would remove.

`rebillable_entries` is the number this exists for: cache entries that
will **cost money again** because of this prune. Its meaning is exact per
area, and each is a different claim:

- `manifests` — every dropped entry re-bills, so it equals the candidate
  count.
- `content` — entries whose recorded response names an asset that resolves
  (through the `url -> hash` index) to a blob being dropped. Those become
  *unmaterializable* from cache; they re-download if fal still serves the
  URL and re-render if it does not, and falaw cannot tell which from here.
  It mirrors the predicate [`falaw.plan.execute()`](falaw.plan.html.md#falaw.plan.execute) applies to a hit from
  the **built-in** converter. It is therefore an *upper* bound, not an exact
  population: with a custom `artifact_converter=` the entry is never
  dropped (it returns a broken artifact instead), and with
  `fetch_bytes=False` dropping the blob changes nothing. Both errors are
  overcounts — the safe direction for a number you read before spending.
- `assets` — only the copies whose blob is *also* gone. While the blob
  survives, re-materializing is a local copy and costs nothing.

`unreferenced_candidates` is the other half of the story, and only
`content` populates it: blobs that **no manifest points at**. falaw cannot
tell whether such a blob is garbage or the last copy of something
irreplaceable — [`falaw.materialize_asset()`](falaw.html.md#falaw.materialize_asset) puts reference images and
locally-rendered `file://` media in the same store, and those never had a
fal response behind them. Counting them as `rebillable` would be wrong
(no cache entry re-bills), but reporting nothing would tell an operator the
prune is free when it may be destroying the only copy of a reference image.

#### *property* freed_bytes *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Bytes actually freed — or, under `dry_run`, that would be freed.

Sums `deleted`, **not** `candidates`. A deletion that failed (a
read-only volume, a permission error) leaves its bytes on disk, and a
capacity tool that reports them as reclaimed tells an operator staring
at a full disk that the problem is solved when it is not.

#### summary()

A human-readable line, phrased in the tense the run actually was.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.prune.cache_usage()

Disk usage of the falaw cache, broken down by area.

The structured form behind [`falaw.cache_stats()`](falaw.html.md#falaw.cache_stats). Read the module
docstring for what each area costs to reclaim.

* **Return type:**
  [`CacheUsage`](#falaw.prune.CacheUsage)

### falaw.prune.prune_assets(, older_than=None, max_bytes=None, dry_run=True, store=None)

Reclaim materialized asset copies — the cheapest disk in the cache (falaw#22).

`assets/` holds a **copy** of each blob rather than a hard link, which is
deliberate ([`falaw.content.write_blob_to_file()`](falaw.content.html.md#falaw.content.write_blob_to_file) explains why a link
would let a consumer corrupt the content store) but doubles the on-disk cost
of every materialized asset. That makes this the prune to reach for first:
while a blob survives, re-materializing its asset is a local copy and costs
nothing, so `rebillable_entries` counts only the copies whose blob is
*also* gone.

* **Parameters:**
  * **older_than** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – drop copies last written more than this ago — seconds, or a
    [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta).
  * **max_bytes** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – drop oldest-first until the area fits in this budget.
  * **dry_run** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – report without deleting. Default, deliberately.
  * **store** – injected `lacing.ArtifactStore`, used only to ask whether
    each dropped copy still has a blob behind it; defaults to
    [`falaw.content.default_content_store()`](falaw.content.html.md#falaw.content.default_content_store).
* **Returns:**
  with `area="assets"`.
* **Return type:**
  [`PruneReport`](#falaw.prune.PruneReport)
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – neither bound was given.

### falaw.prune.prune_content(, older_than=None, max_bytes=None, dry_run=True, store=None)

Reclaim content-addressed blobs — the gigabytes (falaw#22).

This is the **expensive** prune. A blob is the last copy of an asset once
fal has expired its URL (“expired files are permanently deleted and cannot
be recovered”), so dropping one can turn a free cache hit into a re-rendered
clip. The report says how many entries that applies to *before* you commit;
read `rebillable_entries`.

* **Parameters:**
  * **older_than** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – drop blobs last written more than this ago — seconds, or a
    [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta).
  * **max_bytes** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – drop oldest-first until the area fits in this budget.
  * **dry_run** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – report without deleting. Default, deliberately.
  * **store** – injected `lacing.ArtifactStore`; defaults to
    [`falaw.content.default_content_store()`](falaw.content.html.md#falaw.content.default_content_store), whose deletes remove
    the file. An injected store keeps its own backend’s delete policy:
    a stock `ArtifactStore.from_directory` store moves each blob to
    the OS trash, which frees no space on that volume even though the
    report counts the bytes as freed.
* **Return type:**
  [*PruneReport*](#falaw.prune.PruneReport)

Blobs are listed and deleted through lacing’s contained
`iter_blobs`/`delete_blob` (falaw#66): nothing outside the blob root is
listed or removed, and an in-root symlink is unlinked, never its target.

* **Returns:**
  with `area="content"`.
* **Return type:**
  [`PruneReport`](#falaw.prune.PruneReport)
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – neither bound was given — see `_require_a_bound()`.

Both bounds may be combined; a blob selected by either is dropped.

```pycon
>>> report = prune_content(older_than=timedelta(days=90))
>>> report.dry_run
True
```

### falaw.prune.prune_manifests(, older_than=None, max_bytes=None, dry_run=True)

Reclaim cache entries — the fal responses themselves (falaw#22).

Manifests are kilobytes, so this is rarely where the disk is; it is here
because a stale *entry* is its own problem — it pins a model version and a
price you may no longer want served from cache.

Unlike [`prune_content()`](#falaw.prune.prune_content), the cost is unconditional: every dropped
entry re-bills its call on the next run, so `rebillable_entries` always
equals the candidate count.

* **Parameters:**
  * **older_than** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – drop entries stored more than this ago — seconds, or a
    [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta). Read from the manifest’s own
    `stored_at`, falling back to file mtime.
  * **max_bytes** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – drop oldest-first until the area fits in this budget.
  * **dry_run** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – report without deleting. Default, deliberately.
* **Returns:**
  with `area="manifests"`.
* **Return type:**
  [`PruneReport`](#falaw.prune.PruneReport)
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – neither bound was given.

Only the manifest is removed; blobs are shared by content hash across
entries and are never dropped from here — the same rule
[`falaw.drop_cache_entry()`](falaw.html.md#falaw.drop_cache_entry) follows.
