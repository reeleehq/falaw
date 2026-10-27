# falaw.cache

Content-addressed cache for fal calls.

Why this exists: the directorial workflow (“a single edit, the scene
re-renders around it”) only works if unchanged beats *don’t* re-render.
A cache hit is the difference between a 30-second edit-and-preview
loop and a 5-minute one.

Design:

* Key = SHA256 of (model_id, sorted(arguments_json)). Two structurally
  identical fal calls collapse to the same key.
* Value = the raw fal response, plus optional locally-downloaded asset
  paths. We persist both the JSON manifest and the binary downloads.
* Cache root: `$FALAW_CACHE_DIR` or `$FALAW_DATA_DIR/cache` or
  `~/.config/falaw/cache`.
* The cache is *per-process* aware via lru_cache for hot lookups;
  on-disk for persistence across runs.

**The key arguments are not always the wire arguments.** A chained plan
(`generate_image` → `image_to_video`) sends fal a *URL* for the upstream
image, but a URL is minted fresh per upload — so keying on it guarantees a
miss the moment the upstream is genuinely re-executed, and the miss re-bills
the expensive downstream call for unchanged work. [`cached_call_fal()`](#falaw.cache.cached_call_fal)
therefore takes an optional `key_arguments`: the same call with upstream
references resolved to **content hashes** (`sha256:<hex>`) instead of URLs.
See [`falaw.content`](falaw.content.html.md#module-falaw.content) for how those hashes are produced.

Usage:

> from falaw.cache import cached_call_fal
> raw = cached_call_fal(“fal-ai/flux/dev”, {“prompt”: “…”})

The wrapped variant has the same signature as `core.call_fal` but skips
the network when the (model_id, arguments) tuple was seen before.

### Module Attributes

| [`ASSETS_DIRNAME`](#falaw.cache.ASSETS_DIRNAME)   | Sub-directory of the falaw cache holding [`materialize_asset()`](#falaw.cache.materialize_asset) copies.   |
|-------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|

### Functions

| [`cache_get`](#falaw.cache.cache_get)(application, arguments, \*[, ...])       | Return the raw fal response if cached, else None.                       |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`cache_put`](#falaw.cache.cache_put)(application, arguments, raw, \*[, ...])  | Persist a fal response.                                                 |
| [`cache_stats`](#falaw.cache.cache_stats)()                                      | Quick summary of the cache: entry count, disk usage, and where it went. |
| [`cached_call_fal`](#falaw.cache.cached_call_fal)(application, arguments, \*[, ...]) | Call a fal model, but reuse the cached response when present.           |
| [`drop_cache_entry`](#falaw.cache.drop_cache_entry)(application, arguments, \*)       | Delete the cache entry for `(application, arguments)`.                  |
| [`emit_cache_hit`](#falaw.cache.emit_cache_hit)(application[, on_event])            | Emit the synthetic `cache_hit` progress event for `application`.        |
| [`materialize_asset`](#falaw.cache.materialize_asset)(url, \*[, key_hint, store, ...]) | Download a remote asset to the cache and return the local path.         |

### falaw.cache.ASSETS_DIRNAME *= 'assets'*

Sub-directory of the falaw cache holding [`materialize_asset()`](#falaw.cache.materialize_asset) copies.

Named here rather than in [`falaw.prune`](falaw.prune.html.md#module-falaw.prune) because `_asset_path()` is
what decides the layout; the prune side reads this so the two cannot drift.

### falaw.cache.cache_get(application, arguments, , backend='fal', key_extra=None)

Return the raw fal response if cached, else None.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### falaw.cache.cache_put(application, arguments, raw, , note='', wire_arguments=None, backend='fal', key_extra=None)

Persist a fal response. Returns the entry directory path.

* **Parameters:**
  * **application** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – fal model id.
  * **arguments** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]) – the arguments the entry is **keyed** on.
  * **raw** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – the fal response to store.
  * **note** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – free-form label recorded in the manifest.
  * **wire_arguments** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]) – the arguments actually sent to fal, when they differ
    from the key arguments (chained calls send URLs but are keyed on
    content hashes). Recorded for debugging only — it never affects
    the key.
  * **backend** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – which execution backend produced `raw` (falaw#15). Joins
    the cache key only when non-default, same rule as
    [`falaw.canonical.cache_key_payload()`](falaw.canonical.html.md#falaw.canonical.cache_key_payload); recorded in the
    manifest under the same condition, for debugging.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

The manifest is written to a temporary file and moved into place with
[`os.replace()`](https://docs.python.org/3/library/os.html#os.replace), so a reader never sees a half-written entry. That is not
hypothetical since `execute_plan(concurrency=N)`: two calls of one Plan
that are structurally identical land on the same key, and an interleaved
`json.dump` would leave a permanently unparseable entry — a cache that
poisons itself under exactly the fan-out it exists to make cheap.

### falaw.cache.cache_stats()

Quick summary of the cache: entry count, disk usage, and where it went.

`areas` is the part worth reading. Since falaw#14 the cache holds the
*bytes* of every generated asset, so a total on its own cannot distinguish
gigabytes of irreplaceable blobs from gigabytes of `assets/` copies that
cost nothing to regenerate — and only the second is safe to reclaim without
thinking. Each area’s economics, and the primitives that reclaim it, are in
[`falaw.prune`](falaw.prune.html.md#module-falaw.prune).

`size_bytes` is every byte under the cache root, unchanged in meaning from
before the breakdown existed: the `other` area absorbs whatever the named
areas do not claim, so the areas always sum to the whole.

(`+SKIP`ed — it reads the caller’s real cache, a multi-gigabyte walk on
the production box. `tests.test_prune` pins this against a throwaway
cache instead.)

```pycon
>>> stats = cache_stats()
>>> sorted(stats["areas"])
['assets', 'content', 'manifests', 'other', 'scenes', 'url_index']
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.cache.cached_call_fal(application, arguments, , key_arguments=None, refresh=False, on_event=None, backend='fal', key_extra=None)

Call a fal model, but reuse the cached response when present.

* **Parameters:**
  * **application** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – fal model id.
  * **arguments** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]) – model input dict — what is sent **on the wire**.
  * **key_arguments** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]) – what the cache entry is **keyed** on, when that differs
    from what goes on the wire. Defaults to `arguments`. The split
    exists because a chained call must send fal an expiring URL for its
    upstream input while being keyed on that input’s *content hash*, so
    a byte-identical upstream regeneration hits instead of re-billing.
  * **refresh** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – if True, bypass the cache and overwrite it with a fresh result.
  * **on_event** – Per-call subscriber for [`falaw.events.ProgressEvent`](falaw.events.html.md#falaw.events.ProgressEvent).
    On a cache hit, a synthetic `cache_hit` event is emitted so
    UIs can show “skipped” instead of “running”. On a call that ran, the
    `done` event’s `metrics` carries fal’s run metrics (e.g.
    `inference_time`); a hit has none, since nothing ran.
  * **backend** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – which execution backend serves this call (falaw#15) —
    resolved via [`falaw.backends`](falaw.backends.html.md#module-falaw.backends). Also joins the cache key
    (non-default only), so two backends never share an entry. Despite
    the name, this function is no longer fal-specific; the name is
    kept because “fal” is still the only backend and every existing
    call site already spells it this way.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  Raw response (whether from cache or network).

### falaw.cache.drop_cache_entry(application, arguments, , backend='fal', key_extra=None)

Delete the cache entry for `(application, arguments)`. Returns whether one existed.

The counterpart to [`cache_put()`](#falaw.cache.cache_put), and the mechanism that keeps a cache
from becoming a *trap*. An entry whose response can no longer be turned
into a usable artifact — fal deleted the URL and the bytes are not in the
content store — must be a **miss**, not a permanent failure: without this,
escaping one dead call means re-running the whole plan.
[`falaw.plan.execute()`](falaw.plan.html.md#falaw.plan.execute) calls it.

The plan-level escapes are `execute_plan(plan, refresh=True)`, which
re-runs every call and **keeps** what it pays for, and
`execute_plan(plan, use_cache=False)`, which re-runs and keeps nothing —
so the second one bills again on the next run (falaw#49). Neither is a
substitute for this function: both re-bill *every* call in the plan, and
this drops the one entry that actually went bad.

Only the manifest is removed. Blobs in the content store are shared by
content hash across entries and are never dropped from here.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### falaw.cache.emit_cache_hit(application, on_event=None)

Emit the synthetic `cache_hit` progress event for `application`.

Shared by [`cached_call_fal()`](#falaw.cache.cached_call_fal) and [`falaw.plan.execute()`](falaw.plan.html.md#falaw.plan.execute) (which
drives the cache directly, because it must decide whether a hit is
*usable* before committing to it) so a UI sees one event shape either way.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### falaw.cache.materialize_asset(url, , key_hint='', store=None, fetcher=None, refresh=False)

Download a remote asset to the cache and return the local path.

The local filename is content-addressed by the asset’s **bytes**, so two
URLs serving identical bytes resolve to one file. The extension is a
presentational hint for ffmpeg/PIL; the SHA-256 is the address.

Repeat calls are cheap, in three widening circles — this is what makes it
safe to call from a loop over 200 shots:

1. the file is already on disk here (no store lookup, no network) —
   **immutable URLs only**, see below;
2. the bytes are in the content store (no network, or one validating
   round-trip) — so it still works after fal has expired the URL;
3. otherwise, one download.

Circle 1 matters on its own: the content store is prunable, so an asset
can survive as a materialized file after its blob is gone.

**Circle 1 is taken only when the URL cannot change** — that is,
[`falaw.content.is_immutable_url()`](falaw.content.html.md#falaw.content.is_immutable_url) — because reaching it requires
trusting the `url -> hash` index to name the *current* bytes, and for an
arbitrary caller-supplied URL it does not (thorwhalen/falaw#23). A mutable
URL goes to circle 2, where [`falaw.content.content_ref_for_url()`](falaw.content.html.md#falaw.content.content_ref_for_url)
revalidates before reusing anything; when the bytes really are unchanged
that costs one conditional request and still no download, and when they
have changed you get the new file instead of silently getting the old one.

* **Parameters:**
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – the remote asset URL. `file://` is supported and is used
    deliberately by downstream packages for locally-rendered media.
  * **key_hint** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – optional human-readable filename prefix.
  * **store** – injected `lacing.ArtifactStore`; defaults to
    [`falaw.content.default_content_store()`](falaw.content.html.md#falaw.content.default_content_store).
  * **fetcher** – injected byte source (`url -> Iterable[bytes]`); defaults to
    the `urllib`-based one. The seam for custom transport (auth
    headers, retries) and for a hermetic test suite.
  * **refresh** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – re-fetch unconditionally, skipping every circle. Rarely needed
    now: a mutable URL revalidates on its own (falaw#23), so this is for
    an origin that lies about its validators.
* **Raises:**
  [**FalAssetFetchError**](falaw.errors.html.md#falaw.errors.FalAssetFetchError) – the bytes could not be retrieved.
      Unlike a generated-media artifact (which degrades to URL-only —
      see [`falaw.plan.execute()`](falaw.plan.html.md#falaw.plan.execute)), there is nothing to degrade to
      here: the caller asked for a local file.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
