# falaw.testing

Make a suite that uses falaw genuinely offline — the fake asset transport.

falaw content-addresses every media result ([`falaw.content`](falaw.content.html.md#module-falaw.content)): a fal URL is
neither unique-per-content nor durable, so it cannot be an identity, and
[`falaw.execute_plan()`](falaw.html.md#falaw.execute_plan) therefore **reads the bytes** behind every result. A
downstream suite that stubs the fal *response* but not the *asset transport* is
consequently resolving its made-up URLs for real — one DNS lookup and one
connection attempt per test.

Such a suite passes anyway. That is the trap. falaw deliberately degrades a
failed asset fetch to a URL-only artifact with a [`UserWarning`](https://docs.python.org/3/builtins/exceptions.html#UserWarning) rather
than raising, so an upstream hiccup cannot throw away a render fal has already
billed for — which means reaching the network is *invisible* downstream. The
costs are real all the same: the suite is slower and behaves differently
without a network; it exercises the *degraded* path rather than the content
addressing it appears to exercise; and a stub URL whose host happens to answer
**200** pulls arbitrary internet content into the cache with the test still
green.

This module is falaw’s answer, so no consumer has to write one. Three autouse
fixtures, each re-exportable into a `conftest.py` in one line:

```pycon
>>> from falaw.testing import (
...     fake_assets,
...     isolated_falaw_cache,
...     no_outbound_network,
... )  # noqa: F401
```

[`fake_assets()`](#falaw.testing.fake_assets)
: Serves falaw’s asset fetches from memory. An unregistered URL yields
  deterministic synthetic bytes derived from the URL, so two different stub
  URLs behave like two genuinely different renders;
  [`FakeAssets.serve()`](#falaw.testing.FakeAssets.serve) pins explicit bytes — which is how a test makes
  two *different* URLs serve the *same* bytes, the case content addressing
  exists for; [`FakeAssets.fail()`](#falaw.testing.FakeAssets.fail) makes a URL 404, as an expired fal
  asset does, which is how a test exercises the degrade path on purpose.

[`isolated_falaw_cache()`](#falaw.testing.isolated_falaw_cache)
: Points falaw’s manifest cache, content store and url-index at a throwaway
  directory. A precondition for the fake, not a nicety: once the fetches
  *succeed*, an un-isolated run durably records synthetic test bytes under
  real-looking URLs in the developer’s own `~/.config/falaw/cache`.

[`no_outbound_network()`](#falaw.testing.no_outbound_network)
: The backstop. The other two close the holes we know about; this one
  notices the next one. Every non-loopback DNS lookup or socket connect is
  refused **and recorded**, and the recording fails the test at teardown.

**Refusing is not reporting**, and that distinction is the whole design of the
guard. A guard that only raises is invisible here, because falaw’s fetch path
is a funnel of broad `except Exception` handlers that exist for good reasons:
`_fetch_into_store` turns any `Exception` into a `FalAssetFetchError`,
which `execute` then **degrades** to a URL-only artifact with a warning
(rather than discard a render fal has already billed); `remembered_ref`
treats any `Exception` as a cache miss; `make_call_plan`’s cache probe
falls back to `"unknown"`. An ordinary-`Exception` refusal is absorbed by
all three, and the suite stays green with the regression back in place.

Hence two measures, not one. [`OutboundNetworkAttempt`](#falaw.testing.OutboundNetworkAttempt) derives from
[`BaseException`](https://docs.python.org/3/builtins/exceptions.html#BaseException) so it escapes those funnels (`execute_isolated`
deliberately re-raises a non-`Exception`, since a run-level abort is not a
call failure) — and every attempt is **recorded** anyway, because that only
covers the funnels *inside falaw*. A consumer’s own `except BaseException`
re-absorbs it, and a subprocess is out of reach entirely. The record is the
part that cannot be swallowed.

## Why not `FALAW_FETCH_ARTIFACT_BYTES=0`

It silences the network too — by turning content addressing **off**. The suite
becomes hermetic and simultaneously stops testing the feature: every
`asset_id` becomes a response digest rather than a content hash, and no test
covers the path production takes. Faking the transport keeps content addressing
under test with bytes the test controls. See
[`falaw.plan.FETCH_BYTES_ENVVAR`](falaw.plan.html.md#falaw.plan.FETCH_BYTES_ENVVAR).

## Opting a test back into the real world

A test carrying any marker in [`DFLT_LIVE_MARKERS`](#falaw.testing.DFLT_LIVE_MARKERS) (`live_api`) gets the
real transport and no network guard, and keeps the cache isolation. Suites with
another such marker build their own fixtures from the factories:

```pycon
>>> gated = make_fake_assets_fixture(live_markers=("live_api", "live_capture"))
```

The classes and context managers here need no pytest; only the fixtures do.

### Module Attributes

| [`DFLT_LIVE_MARKERS`](#falaw.testing.DFLT_LIVE_MARKERS)                           | Pytest markers meaning "this test is allowed to reach the real world".   |
|----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`DFLT_SYNTHETIC_PREFIX`](#falaw.testing.DFLT_SYNTHETIC_PREFIX)                       | Prefix of the stand-in bytes an unpinned URL serves.                     |
| [`LOCAL_HOSTNAMES`](#falaw.testing.LOCAL_HOSTNAMES)                             | Hostnames that mean "this machine" without a DNS round-trip.             |
| [`NON_NETWORK_SCHEMES`](#falaw.testing.NON_NETWORK_SCHEMES)                         | URL schemes that do not leave this machine, and so are not faked.        |
| [`fake_assets`](#falaw.testing.fake_assets)(request)                        | Autouse fixture serving falaw's asset fetches from memory.               |
| [`isolated_falaw_cache`](#falaw.testing.isolated_falaw_cache)(tmp_path, monkeypatch) | Autouse fixture pointing falaw's on-disk state at a throwaway directory. |
| [`no_outbound_network`](#falaw.testing.no_outbound_network)(request)                | Autouse fixture failing any test that reaches a non-loopback address.    |

### Functions

| [`blocked_outbound_network`](#falaw.testing.blocked_outbound_network)()                        | Refuse **and record** every non-local socket use; yield the record.                                          |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| [`fake_assets`](#falaw.testing.fake_assets)(request)                              | Autouse fixture serving falaw's asset fetches from memory.                                                   |
| [`is_network_url`](#falaw.testing.is_network_url)(url)                               | True when resolving `url` would leave this machine.                                                          |
| [`isolated_falaw_cache`](#falaw.testing.isolated_falaw_cache)(tmp_path, monkeypatch)       | Autouse fixture pointing falaw's on-disk state at a throwaway directory.                                     |
| [`make_fake_assets_fixture`](#falaw.testing.make_fake_assets_fixture)(\*[, live_markers, ...]) | Build a `fake_assets` fixture with non-default settings.                                                     |
| [`make_isolated_falaw_cache_fixture`](#falaw.testing.make_isolated_falaw_cache_fixture)(\*[, autouse])  | Build an `isolated_falaw_cache` fixture.                                                                     |
| [`make_no_outbound_network_fixture`](#falaw.testing.make_no_outbound_network_fixture)(\*[, ...])       | Build a `no_outbound_network` fixture.                                                                       |
| [`no_outbound_network`](#falaw.testing.no_outbound_network)(request)                      | Autouse fixture failing any test that reaches a non-loopback address.                                        |
| [`serving_fake_assets`](#falaw.testing.serving_fake_assets)([assets])                     | Install a [`FakeAssets`](#falaw.testing.FakeAssets) as falaw's transport for the duration. |
| [`synthetic_asset_bytes`](#falaw.testing.synthetic_asset_bytes)(url, \*[, prefix])          | Deterministic stand-in bytes for a URL nothing has pinned.                                                   |

### Classes

| [`FakeAssets`](#falaw.testing.FakeAssets)(\*[, synthetic_prefix, ...])   | An in-memory `url -> bytes` transport standing in for the network.   |
|--------------------------------------------------------------------------------------------|----------------------------------------------------------------------|

### Exceptions

| [`OutboundNetworkAttempt`](#falaw.testing.OutboundNetworkAttempt)   | An offline test tried to talk to a non-local host.   |
|---------------------------------------------------------------------------|------------------------------------------------------|

### falaw.testing.DFLT_LIVE_MARKERS *= ('live_api',)*

Pytest markers meaning “this test is allowed to reach the real world”.

falaw’s own convention. A suite using another name (`live_capture`, say)
passes its own tuple to the fixture factories rather than editing this.

### falaw.testing.DFLT_SYNTHETIC_PREFIX *= 'falaw-test-asset'*

Prefix of the stand-in bytes an unpinned URL serves.

Only ever seen while debugging — which is exactly why it is worth setting per
suite (`FakeAssets(synthetic_prefix="nw-test-asset")`): a hexdump in a
failing assertion then names the suite that invented the bytes.

### *class* falaw.testing.FakeAssets(, synthetic_prefix='falaw-test-asset', fake_non_network_urls=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

An in-memory `url -> bytes` transport standing in for the network.

Install it with [`falaw.content.using_url_fetcher()`](falaw.content.html.md#falaw.content.using_url_fetcher) (the
[`fake_assets()`](#falaw.testing.fake_assets) fixture does), after which every falaw entry point that
reads asset bytes is served from here.

Three behaviours, each of which a downstream suite discovered it needed:

- an **unpinned** network URL yields [`synthetic_asset_bytes()`](#falaw.testing.synthetic_asset_bytes);
- [`serve()`](#falaw.testing.FakeAssets.serve) **pins** explicit bytes, which is how a test makes two
  *different* URLs serve the *same* bytes — the case content addressing
  exists for — or aligns falaw’s view of an asset with bytes the test also
  wrote to disk itself;
- [`fail()`](#falaw.testing.FakeAssets.fail) makes a URL **404**, as an expired fal asset does, which is
  how a test exercises falaw’s degrade-to-URL-only path on purpose.

Every fetch is **recorded** in `fetched`, and that is not a
convenience. falaw degrades a failed fetch to a URL-only artifact with a
warning rather than raising, so a fake that only *refused* an unexpected
URL would be swallowed and the test would pass. Assert on what was fetched,
not on an exception:

```pycon
>>> from lacing import ArtifactStore
>>> from falaw import content_ref_for_url
>>> from falaw.content import using_url_fetcher
>>> store, assets = ArtifactStore.in_memory(), FakeAssets()
>>> shared = assets.serve("https://fal.media/one.png", b"identical bytes")
>>> _ = assets.serve("https://fal.media/two.png", shared)
>>> with using_url_fetcher(assets.chunks):
...     one = content_ref_for_url("https://fal.media/one.png", store=store)
...     two = content_ref_for_url("https://fal.media/two.png", store=store)
>>> one.content_hash == two.content_hash  # two URLs, one content address
True
>>> assets.fetched
['https://fal.media/one.png', 'https://fal.media/two.png']
```

#### chunks(url, , chunk_size=65536)

Yield `url`’s bytes — the [`falaw.content.UrlFetcher`](falaw.content.html.md#falaw.content.UrlFetcher) to install.

* **Raises:**
  [**HTTPError**](https://docs.python.org/3/library/urllib.error.html#urllib.error.HTTPError) – `url` was marked with [`fail()`](#falaw.testing.FakeAssets.fail).
* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]

#### conditional_fetch(url, validators, , chunk_size=65536)

Answer a revalidation — the capability falaw#23 asks a transport for.

Present so a downstream suite exercises the **cheap** path rather than
the fallback. Without it falaw can never confirm a mutable URL is
unchanged, so it re-fetches on every call: correct, but it would mean no
test in the ecosystem ever covers the `304` branch, and any suite
asserting “did not refetch” for a non-fal URL would fail for a reason
that has nothing to do with what it is testing.

Deferred to [`chunks()`](#falaw.testing.FakeAssets.chunks) for a URL this fake does not handle, so a
real `file://` still reaches the real filesystem.

#### etag_for(url)

The ETag this fake serves for `url` — a digest of its current bytes.

A well-behaved origin’s ETag changes exactly when the body does, so
deriving it from the served bytes is the most faithful fake available:
[`serve()`](#falaw.testing.FakeAssets.serve)-ing different bytes at the same URL flips it, and serving
the same bytes twice does not.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### fail(url)

Make `url` 404, the way an expired fal asset does.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### handles(url)

Whether this transport answers for `url` rather than deferring.

A pinned URL always. An unpinned one only when it is a network URL (or
`fake_non_network_urls` is set) — see [`NON_NETWORK_SCHEMES`](#falaw.testing.NON_NETWORK_SCHEMES).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### revalidated *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

URLs answered with a cheap “unchanged” — no body transferred.

Separate from `fetched` because the two are the *point* of
falaw#23 and a suite must be able to tell them apart. Without this, “we
revalidated cheaply” and “we never asked at all” are indistinguishable,
and every cheap-path assertion in the suite is equally satisfied by the
un-fixed code that simply trusted its index.

#### serve(url, data)

Make `url` serve exactly `data`. Returns `data`, for chaining.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

#### synthetic(url)

The bytes an unpinned `url` serves.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### falaw.testing.LOCAL_HOSTNAMES *= frozenset({'', 'ip6-localhost', 'ip6-loopback', 'localhost', 'localhost.localdomain'})*

Hostnames that mean “this machine” without a DNS round-trip.

### falaw.testing.NON_NETWORK_SCHEMES *= frozenset({'', 'file'})*

URL schemes that do not leave this machine, and so are not faked.

`file://` is a documented falaw input — downstream packages hand it locally
rendered media that way — so faking it would replace a real mp4 with synthetic
bytes and break the ffmpeg that reads it. Such URLs fall through to the real
fetcher unless a test pins them explicitly.

### *exception* falaw.testing.OutboundNetworkAttempt

Bases: [`BaseException`](https://docs.python.org/3/builtins/exceptions.html#BaseException)

An offline test tried to talk to a non-local host.

Derived from [`BaseException`](https://docs.python.org/3/builtins/exceptions.html#BaseException), not [`Exception`](https://docs.python.org/3/builtins/exceptions.html#Exception), on purpose:
the fetch path is a funnel of `except Exception` handlers that turn a
failed fetch into a degraded-but-successful result (falaw’s URL-only
artifact fallback is the main one), so anything catchable would be caught.

That still is not enough on its own. It escapes *falaw’s* funnels, not a
consumer’s own `except BaseException` — and not a subprocess, which opens
its own sockets where nothing here has reach. Which is why every attempt is
also **recorded**; see [`blocked_outbound_network()`](#falaw.testing.blocked_outbound_network).

### falaw.testing.blocked_outbound_network()

Refuse **and record** every non-local socket use; yield the record.

The yielded list is the point. Raising alone is not a guard here: falaw
swallows a failed fetch by design, and a refusal that reaches a consumer’s
own broad `except` — or happens in a subprocess — vanishes without trace.
A caller asserts on the list afterwards; [`no_outbound_network()`](#falaw.testing.no_outbound_network) fails
the test at teardown when it is non-empty.

A test that *means* to provoke an attempt drains the list
(`attempts.clear()`) instead of failing.

Blind spot worth knowing: a subprocess opens its own sockets in its own
process, where this has no reach. ffmpeg is the one that matters.

(`.invalid` is reserved by RFC 2606 and can never resolve, so even a
broken guard cannot turn this example into real traffic.)

```pycon
>>> import socket
>>> with blocked_outbound_network() as attempts:
...     try:
...         socket.getaddrinfo("nowhere.invalid", 443)
...     except OutboundNetworkAttempt:
...         pass
>>> attempts
["a DNS lookup for 'nowhere.invalid'"]
```

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)]

### falaw.testing.fake_assets(request)

Autouse fixture serving falaw’s asset fetches from memory.

Re-export it into a `conftest.py` and the whole suite is covered:

```default
from falaw.testing import fake_assets  # noqa: F401
```

Yields the [`FakeAssets`](#falaw.testing.FakeAssets) in force, so a test can pin bytes
(`fake_assets.serve(url, data)`), 404 a URL (`fake_assets.fail(url)`) or
assert on what was fetched (`fake_assets.fetched`). Yields `None` for a
test marked `live_api`, which gets the real transport.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`FakeAssets`](#falaw.testing.FakeAssets)]]

### falaw.testing.is_network_url(url)

True when resolving `url` would leave this machine.

```pycon
>>> is_network_url("https://fal.media/x.png")
True
>>> is_network_url("file:///tmp/rendered.mp4"), is_network_url("/tmp/x.mp4")
(False, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### falaw.testing.isolated_falaw_cache(tmp_path, monkeypatch)

Autouse fixture pointing falaw’s on-disk state at a throwaway directory.

falaw’s manifest cache, content store and url-index all hang off
`$FALAW_CACHE_DIR` / `$FALAW_DATA_DIR`. Without this a run writes into the
developer’s real cache and inherits the previous run’s `url -> content hash`
index — and once [`fake_assets()`](#falaw.testing.fake_assets) makes the fetches *succeed*, it durably
records synthetic test bytes under real-looking URLs there. Yields the root of
the throwaway directory.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### falaw.testing.make_fake_assets_fixture(, live_markers=('live_api',), synthetic_prefix='falaw-test-asset', fake_non_network_urls=False, autouse=True)

Build a `fake_assets` fixture with non-default settings.

[`fake_assets()`](#falaw.testing.fake_assets) is `make_fake_assets_fixture()`. Use this when the
suite’s live-marker names differ, or to label the synthetic bytes with the
suite’s own name:

```pycon
>>> fake_assets = make_fake_assets_fixture(
...     live_markers=("live_api", "live_capture"),
...     synthetic_prefix="reelee-test-asset",
... )
```

### falaw.testing.make_isolated_falaw_cache_fixture(, autouse=True)

Build an `isolated_falaw_cache` fixture. See [`isolated_falaw_cache()`](#falaw.testing.isolated_falaw_cache).

### falaw.testing.make_no_outbound_network_fixture(, live_markers=('live_api',), autouse=True)

Build a `no_outbound_network` fixture. See [`no_outbound_network()`](#falaw.testing.no_outbound_network).

### falaw.testing.no_outbound_network(request)

Autouse fixture failing any test that reaches a non-loopback address.

The backstop behind [`fake_assets()`](#falaw.testing.fake_assets): that one closes the holes we know
about, this one notices the next. Yields the list of recorded attempts, so a
test that means to provoke one can drain it (`no_outbound_network.clear()`)
instead of failing at teardown. Inert for a test marked `live_api`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)]

### falaw.testing.serving_fake_assets(assets=None)

Install a [`FakeAssets`](#falaw.testing.FakeAssets) as falaw’s transport for the duration.

The pytest-free core of [`fake_assets()`](#falaw.testing.fake_assets), for a caller driving falaw
outside a pytest session (a script, a notebook, another test runner).

```pycon
>>> from falaw import materialize_asset
>>> with serving_fake_assets() as assets:
...     _ = assets.serve("https://fal.media/x.png", b"pinned")
...     path = materialize_asset("https://fal.media/x.png")
>>> with open(path, "rb") as f:
...     f.read()
b'pinned'
```

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`FakeAssets`](#falaw.testing.FakeAssets)]

### falaw.testing.synthetic_asset_bytes(url, , prefix='falaw-test-asset')

Deterministic stand-in bytes for a URL nothing has pinned.

Derived from the URL, so two different stub URLs behave like two genuinely
different renders — and the same stub URL hashes the same way on every run,
which is what lets a test assert on a content hash at all.

```pycon
>>> synthetic_asset_bytes("https://fal.media/x.png")
b'falaw-test-asset::https://fal.media/x.png'
>>> a = synthetic_asset_bytes("https://fal.media/one.png")
>>> b = synthetic_asset_bytes("https://fal.media/two.png")
>>> a == b
False
```

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)
