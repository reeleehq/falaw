# falaw.content

Content addressing for fal-produced media — identify a file by *what it is*.

fal serves generated media from a CDN URL, and fal’s own documentation is
explicit that a URL carries neither identity nor durability:

> “Each upload produces a unique URL with no shared namespace.”

> “Expired files are permanently deleted and cannot be recovered.”

So a URL is the wrong handle for the two jobs falaw needs done:

1. **Naming an artifact.** `lacing.Artifact.asset_id` is contractually the
   SHA-256 of the artifact’s *bytes* — “two artifacts with the same
   `asset_id` are byte-identical regardless of where they live”. Hashing the
   URL instead produces a different id for two byte-identical renders and
   silently breaks every consumer that trusts that contract.
2. **Keying a cache.** A byte-identical upstream regeneration must produce a
   downstream cache **hit**. With a URL in the key it produces a miss, and the
   miss re-bills a $0.35–$1.50 clip for work that did not change.

This module is the single place falaw turns a URL into a content hash. It

* streams the bytes into a `lacing.ArtifactStore` blob store — which is
  content-addressed, `dol`-backed and swappable (in-memory / directory /
  object store) — rather than growing a second blob store of its own;
* remembers `url -> (content_hash, bytes_size, validators)` in a small
  on-disk index, so re-executing an already-cached plan does **not** re-download
  anything. The index is a *hint*, never an identity, and it is only \*\*sound for
  immutable URLs\*\* — so falaw decides, per URL, whether it may be trusted
  (thorwhalen/falaw#23):
  - a **fal-served** URL is trusted outright, because fal guarantees a URL is
    minted per upload and therefore never re-points at different bytes;
  - **anything else** — an arbitrary caller-supplied `https://…/reference.png`
    reached through [`falaw.cache.materialize_asset()`](falaw.cache.html.md#falaw.cache.materialize_asset), or a `file://` clip
    that gets re-rendered to the same path — is **revalidated** before reuse: a
    conditional request replaying the recorded `ETag` / `Last-Modified`, or
    a `(mtime, size)` check for a local file. `304` costs a round-trip and
    no payload; a changed asset yields a changed content hash, as it must.

  When falaw *cannot* check — no validators recorded, or an injected transport
  with no conditional-request support — it re-fetches rather than trusting. An
  unverifiable hint is not evidence. [`is_immutable_url()`](#falaw.content.is_immutable_url) is the predicate,
  and `IMMUTABLE_URL_HOSTS` is where you add a host you mint yourself;
* serves the bytes from the store after the URL has expired, so a months-old
  cache hit still yields a usable artifact instead of a dead link.

The blob store is **injected**, never constructed inline by callers:
[`default_content_store()`](#falaw.content.default_content_store) is the falaw-cache-rooted default, and every
public function here takes a `store` keyword so a caller can point falaw at
an S3-backed store without touching any other code.

So is the **transport**. Per call it is the `fetcher=` / `asset_fetcher=`
argument; for a whole process it is [`using_url_fetcher()`](#falaw.content.using_url_fetcher), which covers
[`content_ref_for_url()`](#falaw.content.content_ref_for_url), [`falaw.materialize_asset()`](falaw.html.md#falaw.materialize_asset),
[`falaw.execute_plan()`](falaw.html.md#falaw.execute_plan) and [`falaw.execute_plan_isolated()`](falaw.html.md#falaw.execute_plan_isolated) in one
place. That matters most to *downstream* test suites: falaw content-addresses
every media result, so a suite that stubs the fal response but not the
transport resolves its made-up URLs for real — and stays green while doing it,
because a failed fetch degrades to a URL-only artifact with a warning rather
than raising. [`falaw.testing`](falaw.testing.html.md#module-falaw.testing) ships the fake so no consumer has to write
one.

### Examples

```pycon
>>> from lacing import ArtifactStore
>>> store = ArtifactStore.in_memory()
>>> ref = content_ref_for_url(
...     "https://fal.media/files/one.png",
...     store=store,
...     fetcher=lambda url: [b"pretend-", b"png-bytes"],
... )
>>> ref.bytes_size
17
>>> ref.content_hash == __import__("hashlib").sha256(b"pretend-png-bytes").hexdigest()
True
```

The same bytes served at a *different* URL yield the same reference — which is
the whole point:

```pycon
>>> other = content_ref_for_url(
...     "https://fal.media/files/two.png",
...     store=store,
...     fetcher=lambda url: [b"pretend-png-bytes"],
... )
>>> other.content_hash == ref.content_hash
True
```

### Module Attributes

| [`UrlFetcher`](#falaw.content.UrlFetcher)   | A callable that yields the bytes of a URL in chunks.   |
|---------------------------------------------------------------|--------------------------------------------------------|

### Functions

| [`content_ref_for_url`](#falaw.content.content_ref_for_url)(url, \*[, store, ...])        | Materialize `url`'s bytes into `store` and return their content hash.                                  |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------|
| [`default_content_store`](#falaw.content.default_content_store)()                           | The falaw-cache-rooted `lacing.ArtifactStore`.                                                         |
| [`default_url_fetcher`](#falaw.content.default_url_fetcher)()                             | The transport used when no `fetcher=` argument is given.                                               |
| [`is_immutable_url`](#falaw.content.is_immutable_url)(url)                             | Whether `url` is guaranteed never to serve different bytes later.                                      |
| [`remembered_ref`](#falaw.content.remembered_ref)(url)                               | The [`ContentRef`](#falaw.content.ContentRef) previously recorded for `url`, if any. |
| [`using_url_fetcher`](#falaw.content.using_url_fetcher)(fetcher)                        | Make `fetcher` falaw's default asset transport for the duration.                                       |
| [`write_blob_to_file`](#falaw.content.write_blob_to_file)(content_hash, path, \*[, ...]) | Materialize the blob for `content_hash` as a **copy** at `path`.                                       |

### Classes

| [`ConditionalOutcome`](#falaw.content.ConditionalOutcome)(not_modified[, chunks, ...])   | The result of asking an origin whether a URL's bytes changed.           |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`ContentRef`](#falaw.content.ContentRef)(content_hash, bytes_size)              | A content-addressed handle on some bytes falaw has materialized.        |
| [`Validators`](#falaw.content.Validators)([etag, last_modified])                 | What an origin gave us to ask "are these bytes still current?" cheaply. |

### *class* falaw.content.ConditionalOutcome(not_modified, chunks=None, validators=Validators(etag='', last_modified=''))

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The result of asking an origin whether a URL’s bytes changed.

Either `not_modified` (the remembered content hash still stands, at the
cost of one round-trip and no payload), or the **new** bytes — carried here
rather than re-requested, because a caller that discovers staleness has
already paid for the response body.

### *class* falaw.content.ContentRef(content_hash, bytes_size)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A content-addressed handle on some bytes falaw has materialized.

`content_hash` is the SHA-256 hex digest of the bytes — the value
`lacing.Artifact.asset_id` is contractually required to hold, and the
value that goes into a downstream cache key in place of a URL.

### falaw.content.UrlFetcher

A callable that yields the bytes of a URL in chunks.

The injection seam for tests and for callers that need custom transport
(auth headers, retries, a local mirror). [`default_url_fetcher()`](#falaw.content.default_url_fetcher) resolves
the one in force; [`using_url_fetcher()`](#falaw.content.using_url_fetcher) installs another.

alias of `Callable`[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]]

### *class* falaw.content.Validators(etag='', last_modified='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What an origin gave us to ask “are these bytes still current?” cheaply.

`etag` and `last_modified` are the HTTP response headers of the same
names, replayed as `If-None-Match` / `If-Modified-Since` on the next
read. A `file://` URL has neither, so falaw synthesises an `etag` from
the file’s `(mtime_ns, size)` — see `_file_validators()`. Falsy when
the origin offered nothing, which is the case falaw must treat as
“cannot revalidate”, never as “unchanged”.

### falaw.content.content_ref_for_url(url, , store=None, fetcher=None, refresh=False, assume_immutable=None)

Materialize `url`’s bytes into `store` and return their content hash.

Idempotent and cheap on repeat, but *how* cheap depends on whether the URL
can change behind falaw’s back — and falaw decides that rather than asking
the caller to know (thorwhalen/falaw#23):

1. **Immutable URL** (fal’s own — see [`is_immutable_url()`](#falaw.content.is_immutable_url)) with a
   remembered hash whose blob is present: returned immediately, \*\*no
   network\*\*. This is what makes re-executing an already-cached plan free
   rather than re-downloading every clip.
2. **Mutable URL** with a remembered hash: falaw **revalidates** — a
   conditional `GET` replaying the recorded `ETag` / `Last-Modified`
   (for `file://`, a `(mtime, size)` comparison). A `304` costs one
   round-trip and no payload; a `200` means the bytes really changed and
   the new ones are stored, so the content hash changes with them.
3. **No usable answer** — nothing remembered, no validators recorded, or a
   transport that cannot make conditional requests: a plain fetch.

Step 3 is the important default. A transport that cannot revalidate makes
falaw **re-fetch**, never trust: an unverifiable hint is not evidence.

* **Parameters:**
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The asset URL. `file://` is supported and treated as mutable.
  * **store** – Injected `lacing.ArtifactStore`; defaults to
    [`default_content_store()`](#falaw.content.default_content_store).
  * **fetcher** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]]]) – Injected byte source; defaults to [`default_url_fetcher()`](#falaw.content.default_url_fetcher)
    (the built-in `urllib` transport unless [`using_url_fetcher()`](#falaw.content.using_url_fetcher)
    has installed another). To support revalidation, a custom transport
    exposes a `conditional_fetch(url, validators) -> ConditionalOutcome`
    attribute; without one it is simply never asked.
  * **refresh** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Skip every shortcut and re-fetch unconditionally. Rarely needed
    now that mutable URLs revalidate on their own — keep it for a URL
    whose origin lies about its validators.
  * **assume_immutable** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Override the host-based decision. `True` restores
    the old unconditional trust (use for a host you mint yourself, and
    prefer adding it to `IMMUTABLE_URL_HOSTS`); `False` forces
    revalidation even for fal.
* **Raises:**
  [**FalAssetFetchError**](falaw.html.md#falaw.FalAssetFetchError) – the bytes could not be retrieved, or the response
      was empty. Never returns a reference it could not back with bytes —
      a silent zero-byte “artifact” is the failure mode this guards.
* **Return type:**
  [`ContentRef`](#falaw.content.ContentRef)

### falaw.content.default_content_store()

The falaw-cache-rooted `lacing.ArtifactStore`.

Rooted at `<falaw cache dir>/content`, so it moves with
`$FALAW_CACHE_DIR` / `$FALAW_DATA_DIR` like every other piece of falaw
state. Constructed per call (the constructor only ensures directories
exist) so a test that re-points the cache dir gets a fresh store.

**Deleting a blob removes it from disk** rather than moving it to the OS
trash. `dol.Files` — the blob backend `from_directory` lays down —
trashes by default, including on Linux, which is a kind default for a
user’s own files and the wrong one here: every blob is derived data, and
the only thing in falaw that deletes one is [`falaw.prune.prune_content()`](falaw.prune.html.md#falaw.prune.prune_content),
whose whole job is to give the volume its space back. A trashed blob frees
nothing (the trash usually lives on the same volume) while the prune report
says it did (thorwhalen/falaw#66). The deletion is still an explicit,
`dry_run`-by-default operator act, so the trash was never the safety net.

### falaw.content.default_url_fetcher()

The transport used when no `fetcher=` argument is given.

[`using_url_fetcher()`](#falaw.content.using_url_fetcher)’s installed fetcher if there is one, else the
built-in `urllib`-based one. Resolved at call time, so every falaw entry
point that reads asset bytes — [`content_ref_for_url()`](#falaw.content.content_ref_for_url),
[`falaw.materialize_asset()`](falaw.html.md#falaw.materialize_asset), [`falaw.execute_plan()`](falaw.html.md#falaw.execute_plan) and
[`falaw.execute_plan_isolated()`](falaw.html.md#falaw.execute_plan_isolated) — honours an override installed after
they were imported.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]]

### falaw.content.is_immutable_url(url)

Whether `url` is guaranteed never to serve different bytes later.

True only for hosts falaw knows mint a fresh URL per upload —
`IMMUTABLE_URL_HOSTS`, which is fal’s own CDN out of the box, and any
**subdomain** of one. **Everything else is mutable**, including `file://`:
a locally-rendered clip re-rendered to the same path is the textbook case of
one URL serving two different things.

The default is the safe one on purpose. Guessing “probably immutable” for
an unknown host is what thorwhalen/falaw#23 was: a changed input producing
an unchanged content address, silently, with the stale hash flowing into
`Artifact.asset_id` and every downstream cache key.

Two rules make this a *security* boundary rather than a string comparison,
and both were added after a review reproduced falaw#23 against the first
cut of this function:

1. **The host must be a plain DNS name.** `urlsplit().hostname` is not
   what an HTTP client resolves. Python accepts a backslash (and `%2F`)
   inside a netloc, while WHATWG-conformant clients — including
   `requests`/`urllib3` — treat them as *delimiters*. So
   `http://127.0.0.1:8000\@fal.media/x` parses here with hostname
   `fal.media` and is fetched from `127.0.0.1`. Anything outside
   `[a-z0-9.-]` is therefore refused outright.
2. **Matching is label-wise, never by raw suffix.** `endswith(".fal.media")`
   is true of `evil.com\.fal.media`; `host == h or host.endswith("." + h)`
   is not.

```pycon
>>> is_immutable_url("https://v3b.fal.media/files/x.png")
True
>>> is_immutable_url("https://fal.media/files/x.png")
True
>>> is_immutable_url("https://example.com/reference.png")
False
>>> is_immutable_url("file:///tmp/render.mp4")
False
```

A host that merely *contains* a trusted name is not that host, however it
is spelled:

```pycon
>>> is_immutable_url("https://fal.media@evil.example/x.png")
False
>>> is_immutable_url("https://notfal.media/x.png")
False
>>> is_immutable_url("http://127.0.0.1:8000\\@fal.media/x.png")
False
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### falaw.content.remembered_ref(url)

The [`ContentRef`](#falaw.content.ContentRef) previously recorded for `url`, if any.

A *hint*, not a guarantee: it says “the last time falaw fetched this URL,
the bytes hashed to this” and says nothing about whether those bytes are
still in any store. Callers must verify (`store.has_blob(...)`, or an
already-materialized file on disk) before trusting it.

Public because it is the cheap pre-check that lets a caller answer “do I
already have this?” without a network round-trip — see
[`falaw.cache.materialize_asset()`](falaw.cache.html.md#falaw.cache.materialize_asset).

**It says nothing about whether the URL still serves those bytes.** For a
mutable URL that question needs [`content_ref_for_url()`](#falaw.content.content_ref_for_url), which
revalidates; this is the raw recorded value, and trusting it for a
non-[`is_immutable_url()`](#falaw.content.is_immutable_url) URL is thorwhalen/falaw#23.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`ContentRef`](#falaw.content.ContentRef)]

### falaw.content.using_url_fetcher(fetcher)

Make `fetcher` falaw’s default asset transport for the duration.

The **public seam** for replacing falaw’s network transport wholesale —
with an authenticated client, a retrying one, a local mirror, or (the
common case) an in-memory fake in a test suite.

Prefer this to reaching for the module’s private default: it covers every
entry point in one place, it needs no `monkeypatch`, and it cannot be
invalidated by an internal rename. It is also the only mechanism that
reaches a call falaw makes from a thread you did not create — see
`_DEFAULT_FETCHER` for why that matters.

An explicitly passed `fetcher=` / `asset_fetcher=` still wins: this
changes the *default*, never an explicit choice.

Nests and restores, so an inner block cannot leak over an outer one:

```pycon
>>> from lacing import ArtifactStore
>>> store = ArtifactStore.in_memory()
>>> before = default_url_fetcher()
>>> with using_url_fetcher(lambda url: [b"faked"]):
...     content_ref_for_url("https://fal.media/x.png", store=store).bytes_size
5
>>> default_url_fetcher() is before
True
```

For a ready-made fake with pinned bytes and 404s, see [`falaw.testing`](falaw.testing.html.md#module-falaw.testing).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]]]

### falaw.content.write_blob_to_file(content_hash, path, , store=None)

Materialize the blob for `content_hash` as a **copy** at `path`.

Writes via a temporary file and an atomic rename, so a concurrent reader
never sees a partial file.

## Why a copy and not a hard link

Hard-linking the store’s own blob file would be free, and an earlier cut of
this function did exactly that — but a hard link makes the returned path
and the content-store blob **the same inode**. Any consumer that writes
through the returned path (ffmpeg writing in place, an accidental `open(p,
"ab")`) then leaves a blob whose SHA-256 no longer matches its own name,
while `has_blob` keeps answering `True` — the store starts serving
*wrong bytes under a correct content address*, which is precisely the
failure class content addressing exists to eliminate. Making the link
read-only instead is not an option either: the store’s backend writes blobs
with `open(path, "wb")`, so a read-only blob breaks re-putting identical
bytes.

A copy costs disk (and, on APFS/btrfs/XFS, `shutil.copyfile` gets
copy-on-write for free). Immutability of the content store is worth it.

Returns `path`.

* **raises KeyError:**
  the store holds no blob for `content_hash`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
