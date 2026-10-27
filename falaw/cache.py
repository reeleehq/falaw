"""Content-addressed cache for fal calls.

Why this exists: the directorial workflow ("a single edit, the scene
re-renders around it") only works if unchanged beats *don't* re-render.
A cache hit is the difference between a 30-second edit-and-preview
loop and a 5-minute one.

Design:

* Key = SHA256 of (model_id, sorted(arguments_json)). Two structurally
  identical fal calls collapse to the same key.
* Value = the raw fal response, plus optional locally-downloaded asset
  paths. We persist both the JSON manifest and the binary downloads.
* Cache root: ``$FALAW_CACHE_DIR`` or ``$FALAW_DATA_DIR/cache`` or
  ``~/.config/falaw/cache``.
* The cache is *per-process* aware via lru_cache for hot lookups;
  on-disk for persistence across runs.

**The key arguments are not always the wire arguments.** A chained plan
(``generate_image`` → ``image_to_video``) sends fal a *URL* for the upstream
image, but a URL is minted fresh per upload — so keying on it guarantees a
miss the moment the upstream is genuinely re-executed, and the miss re-bills
the expensive downstream call for unchanged work. :func:`cached_call_fal`
therefore takes an optional ``key_arguments``: the same call with upstream
references resolved to **content hashes** (``sha256:<hex>``) instead of URLs.
See :mod:`falaw.content` for how those hashes are produced.

Usage:

    from falaw.cache import cached_call_fal
    raw = cached_call_fal("fal-ai/flux/dev", {"prompt": "..."})

The wrapped variant has the same signature as `core.call_fal` but skips
the network when the (model_id, arguments) tuple was seen before.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
import warnings
from typing import Any, Mapping, Optional

from .canonical import DFLT_BACKEND, cache_key_payload, canonical_blob, ensure_canonical


# --- cache root -----------------------------------------------------------

ASSETS_DIRNAME = "assets"
"""Sub-directory of the falaw cache holding :func:`materialize_asset` copies.

Named here rather than in :mod:`falaw.prune` because :func:`_asset_path` is
what decides the layout; the prune side reads this so the two cannot drift.
"""


def _cache_dir() -> str:
    base = (
        os.environ.get("FALAW_CACHE_DIR")
        or (
            os.environ.get("FALAW_DATA_DIR")
            and os.path.join(os.environ["FALAW_DATA_DIR"], "cache")
        )
        or os.path.expanduser("~/.config/falaw/cache")
    )
    os.makedirs(base, exist_ok=True)
    return base


def _key(
    application: str,
    arguments: Mapping[str, Any],
    *,
    backend: str = DFLT_BACKEND,
    key_extra: Optional[Mapping[str, Any]] = None,
) -> str:
    # No `default=str` fallback: a hashing function that guesses is a hashing
    # function that collides (falaw#17). Non-canonicalisable arguments raise
    # `FalNonCanonicalArgument` instead of silently sharing (or forever
    # missing) a key. The payload shape lives in `falaw.canonical`, next to
    # `plan_hash`'s, so a new identity-bearing field is added to both at once.
    # `backend` joins the key only when non-default (falaw#15), so every
    # existing "fal" entry keeps its exact key.
    return hashlib.sha256(
        canonical_blob(
            cache_key_payload(
                application, arguments, backend=backend, key_extra=key_extra
            )
        )
    ).hexdigest()


def _entry_dir(key: str) -> str:
    # Two-char shard so the cache directory listing stays manageable.
    d = os.path.join(_cache_dir(), key[:2], key)
    os.makedirs(d, exist_ok=True)
    return d


def _manifest_path(key: str) -> str:
    return os.path.join(_entry_dir(key), "manifest.json")


# --- public API -----------------------------------------------------------


def cache_get(
    application: str,
    arguments: Mapping[str, Any],
    *,
    backend: str = DFLT_BACKEND,
    key_extra: Optional[Mapping[str, Any]] = None,
) -> Optional[dict]:
    """Return the raw fal response if cached, else None."""
    path = _manifest_path(
        _key(application, arguments, backend=backend, key_extra=key_extra)
    )
    if not os.path.exists(path):
        return None
    with open(path) as f:
        manifest = json.load(f)
    return manifest.get("raw")


def cache_put(
    application: str,
    arguments: Mapping[str, Any],
    raw: dict,
    *,
    note: str = "",
    wire_arguments: Optional[Mapping[str, Any]] = None,
    backend: str = DFLT_BACKEND,
    key_extra: Optional[Mapping[str, Any]] = None,
) -> str:
    """Persist a fal response. Returns the entry directory path.

    Args:
        application: fal model id.
        arguments: the arguments the entry is **keyed** on.
        raw: the fal response to store.
        note: free-form label recorded in the manifest.
        wire_arguments: the arguments actually sent to fal, when they differ
            from the key arguments (chained calls send URLs but are keyed on
            content hashes). Recorded for debugging only — it never affects
            the key.
        backend: which execution backend produced ``raw`` (falaw#15). Joins
            the cache key only when non-default, same rule as
            :func:`falaw.canonical.cache_key_payload`; recorded in the
            manifest under the same condition, for debugging.

    The manifest is written to a temporary file and moved into place with
    :func:`os.replace`, so a reader never sees a half-written entry. That is not
    hypothetical since ``execute_plan(concurrency=N)``: two calls of one Plan
    that are structurally identical land on the same key, and an interleaved
    ``json.dump`` would leave a permanently unparseable entry — a cache that
    poisons itself under exactly the fan-out it exists to make cheap.
    """
    key = _key(application, arguments, backend=backend, key_extra=key_extra)
    d = _entry_dir(key)
    manifest = {
        "key": key,
        "application": application,
        "arguments": dict(arguments),
        "raw": raw,
        "note": note,
        "stored_at": time.time(),
    }
    if wire_arguments is not None:
        manifest["wire_arguments"] = dict(wire_arguments)
    if backend != DFLT_BACKEND:
        manifest["backend"] = backend
    path = _manifest_path(key)
    tmp = f"{path}.{uuid.uuid4().hex[:8]}.part"
    try:
        with open(tmp, "w") as f:
            # `default=str` here is display-only, never keyed: `raw` and
            # `wire_arguments` may hold values we render for debugging. But
            # `allow_nan=False` is load-bearing — Python's json would happily
            # write a bare `NaN`, valid to itself and invalid JSON to every
            # strict parser, leaving an on-disk entry nothing else can read.
            json.dump(manifest, f, indent=2, default=str, allow_nan=False)
        os.replace(tmp, path)
    except BaseException:
        _unlink_quietly(tmp)
        raise
    return d


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def drop_cache_entry(
    application: str,
    arguments: Mapping[str, Any],
    *,
    backend: str = DFLT_BACKEND,
    key_extra: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Delete the cache entry for ``(application, arguments)``. Returns whether one existed.

    The counterpart to :func:`cache_put`, and the mechanism that keeps a cache
    from becoming a *trap*. An entry whose response can no longer be turned
    into a usable artifact — fal deleted the URL and the bytes are not in the
    content store — must be a **miss**, not a permanent failure: without this,
    escaping one dead call means re-running the whole plan.
    :func:`falaw.plan.execute` calls it.

    The plan-level escapes are ``execute_plan(plan, refresh=True)``, which
    re-runs every call and **keeps** what it pays for, and
    ``execute_plan(plan, use_cache=False)``, which re-runs and keeps nothing —
    so the second one bills again on the next run (falaw#49). Neither is a
    substitute for this function: both re-bill *every* call in the plan, and
    this drops the one entry that actually went bad.

    Only the manifest is removed. Blobs in the content store are shared by
    content hash across entries and are never dropped from here.
    """
    path = _manifest_path(
        _key(application, arguments, backend=backend, key_extra=key_extra)
    )
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True


def emit_cache_hit(application: str, on_event=None) -> None:
    """Emit the synthetic ``cache_hit`` progress event for ``application``.

    Shared by :func:`cached_call_fal` and :func:`falaw.plan.execute` (which
    drives the cache directly, because it must decide whether a hit is
    *usable* before committing to it) so a UI sees one event shape either way.
    """
    import uuid as _uuid

    from .events import ProgressEvent, emit

    emit(
        ProgressEvent(
            kind="cache_hit",
            application=application,
            call_id=_uuid.uuid4().hex[:12],
        ),
        also=(on_event,) if on_event else (),
    )


def cached_call_fal(
    application: str,
    arguments: Mapping[str, Any],
    *,
    key_arguments: Optional[Mapping[str, Any]] = None,
    refresh: bool = False,
    on_event=None,
    backend: str = DFLT_BACKEND,
    key_extra: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Call a fal model, but reuse the cached response when present.

    Args:
        application: fal model id.
        arguments: model input dict — what is sent **on the wire**.
        key_arguments: what the cache entry is **keyed** on, when that differs
            from what goes on the wire. Defaults to ``arguments``. The split
            exists because a chained call must send fal an expiring URL for its
            upstream input while being keyed on that input's *content hash*, so
            a byte-identical upstream regeneration hits instead of re-billing.
        refresh: if True, bypass the cache and overwrite it with a fresh result.
        on_event: Per-call subscriber for :class:`falaw.events.ProgressEvent`.
            On a cache hit, a synthetic ``cache_hit`` event is emitted so
            UIs can show "skipped" instead of "running". On a call that ran, the
            ``done`` event's ``metrics`` carries fal's run metrics (e.g.
            ``inference_time``); a hit has none, since nothing ran.
        backend: which execution backend serves this call (falaw#15) —
            resolved via :mod:`falaw.backends`. Also joins the cache key
            (non-default only), so two backends never share an entry. Despite
            the name, this function is no longer fal-specific; the name is
            kept because "fal" is still the only backend and every existing
            call site already spells it this way.

    Returns:
        Raw response (whether from cache or network).
    """
    from .backends import get_backend_executor

    from .terms import check_terms, current_terms_context

    # The ambient terms context (falaw#110) covers every eager verb: refuse
    # before the cache is consulted, since a hit also serves the model's output.
    check_terms(application, backend, current_terms_context(), arguments=arguments)
    key_args = arguments if key_arguments is None else key_arguments
    # Refuse while it is still free: on the `refresh=True` path the first key
    # computation would otherwise happen in `cache_put`, *after* the paid call
    # — raising there loses a response fal has already billed for.
    ensure_canonical(dict(key_args), context="key_arguments")
    if not refresh:
        hit = cache_get(application, key_args, backend=backend, key_extra=key_extra)
        if hit is not None:
            emit_cache_hit(application, on_event)
            return hit
    raw = get_backend_executor(backend)(application, arguments, on_event=on_event)
    try:
        cache_put(
            application,
            key_args,
            raw,
            wire_arguments=None if key_arguments is None else arguments,
            backend=backend,
            key_extra=key_extra,
        )
    except Exception as e:
        # A paid result is never discarded (see falaw.plan.execute's failure
        # policy): fal has already run — and billed — this call, so a cache
        # WRITE failure (a response carrying a non-finite float that the
        # strict manifest refuses, a full disk, a permission error) must
        # degrade to "uncached", not destroy the response. On refresh=True the
        # pre-refresh entry is dropped too — the caller explicitly asked for
        # fresh, so letting the old entry keep serving would quietly undo the
        # refresh on every later call.
        if refresh:
            try:
                drop_cache_entry(
                    application, key_args, backend=backend, key_extra=key_extra
                )
            except OSError:
                pass
        warnings.warn(
            f"falaw could not cache the response for {application!r} "
            f"({type(e).__name__}: {e}); returning the billed response "
            "uncached. Until the cause is fixed, re-running this call will "
            "bill again.",
            UserWarning,
            stacklevel=2,
        )
    return raw


def materialize_asset(
    url: str,
    *,
    key_hint: str = "",
    store=None,
    fetcher=None,
    refresh: bool = False,
) -> str:
    """Download a remote asset to the cache and return the local path.

    The local filename is content-addressed by the asset's **bytes**, so two
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
    :func:`falaw.content.is_immutable_url` — because reaching it requires
    trusting the ``url -> hash`` index to name the *current* bytes, and for an
    arbitrary caller-supplied URL it does not (thorwhalen/falaw#23). A mutable
    URL goes to circle 2, where :func:`falaw.content.content_ref_for_url`
    revalidates before reusing anything; when the bytes really are unchanged
    that costs one conditional request and still no download, and when they
    have changed you get the new file instead of silently getting the old one.

    Args:
        url: the remote asset URL. ``file://`` is supported and is used
            deliberately by downstream packages for locally-rendered media.
        key_hint: optional human-readable filename prefix.
        store: injected :class:`lacing.ArtifactStore`; defaults to
            :func:`falaw.content.default_content_store`.
        fetcher: injected byte source (``url -> Iterable[bytes]``); defaults to
            the ``urllib``-based one. The seam for custom transport (auth
            headers, retries) and for a hermetic test suite.
        refresh: re-fetch unconditionally, skipping every circle. Rarely needed
            now: a mutable URL revalidates on its own (falaw#23), so this is for
            an origin that lies about its validators.

    Raises:
        falaw.errors.FalAssetFetchError: the bytes could not be retrieved.
            Unlike a generated-media artifact (which degrades to URL-only —
            see :func:`falaw.plan.execute`), there is nothing to degrade to
            here: the caller asked for a local file.
    """
    # Local import: ``falaw.content`` imports ``_cache_dir`` from this module,
    # so importing it at module scope would be a cycle.
    from .content import (
        content_ref_for_url,
        is_immutable_url,
        remembered_ref,
        write_blob_to_file,
    )
    from .degrade import emit_degradation
    from .errors import FalAssetFetchError

    hint = None if refresh else remembered_ref(url)
    local_hint_path = (
        None if hint is None else _asset_path(url, key_hint, hint.content_hash)
    )
    if (
        local_hint_path is not None
        and is_immutable_url(url)
        and os.path.exists(local_hint_path)
    ):
        return local_hint_path

    try:
        ref = content_ref_for_url(url, store=store, fetcher=fetcher, refresh=refresh)
    except FalAssetFetchError as e:
        # Circle 1 as a *fallback* rather than a shortcut. For a mutable URL we
        # had to try the origin first — returning the old file while a newer one
        # was one request away is falaw#23 — but having tried and found the
        # origin gone, a file sitting right here beats failing. The content
        # store is prunable and fal URLs expire, so a materialized file
        # routinely outlives both.
        if local_hint_path is not None and os.path.exists(local_hint_path):
            emit_degradation(
                f"{url!r} could not be re-read ({e}); returning the copy "
                "materialized earlier. If that URL is mutable, this file may "
                "be superseded."
            )
            return local_hint_path
        raise
    path = _asset_path(url, key_hint, ref.content_hash)
    if os.path.exists(path):
        return path
    return write_blob_to_file(ref.content_hash, path, store=store)


def _asset_path(url: str, key_hint: str, content_hash: str) -> str:
    """Where :func:`materialize_asset` puts the bytes for ``content_hash``."""
    ext = _infer_ext_from_url(url)
    fname = f"{key_hint + '-' if key_hint else ''}{content_hash}{ext}"
    return os.path.join(_cache_dir(), ASSETS_DIRNAME, fname)


def _infer_ext_from_url(url: str) -> str:
    base = url.split("?", 1)[0]
    for ext in (
        ".mp4",
        ".mov",
        ".webm",
        ".mp3",
        ".wav",
        ".m4a",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    ):
        if base.lower().endswith(ext):
            return ext
    return ".bin"


def cache_stats() -> dict:
    """Quick summary of the cache: entry count, disk usage, and where it went.

    ``areas`` is the part worth reading. Since falaw#14 the cache holds the
    *bytes* of every generated asset, so a total on its own cannot distinguish
    gigabytes of irreplaceable blobs from gigabytes of ``assets/`` copies that
    cost nothing to regenerate — and only the second is safe to reclaim without
    thinking. Each area's economics, and the primitives that reclaim it, are in
    :mod:`falaw.prune`.

    ``size_bytes`` is every byte under the cache root, unchanged in meaning from
    before the breakdown existed: the ``other`` area absorbs whatever the named
    areas do not claim, so the areas always sum to the whole.

    (``+SKIP``\\ ed — it reads the caller's real cache, a multi-gigabyte walk on
    the production box. :mod:`tests.test_prune` pins this against a throwaway
    cache instead.)

    >>> stats = cache_stats()                        # doctest: +SKIP
    >>> sorted(stats["areas"])                       # doctest: +SKIP
    ['assets', 'content', 'manifests', 'other', 'scenes', 'url_index']
    """
    # Local import: `falaw.prune` imports `_cache_dir` from this module, so a
    # module-scope import would be a cycle — the same reason
    # `materialize_asset` imports `falaw.content` inside the function body.
    from .prune import cache_usage

    usage = cache_usage()
    return {
        "root": usage.root,
        "manifest_entries": usage.area("manifests").entries,
        "size_bytes": usage.total_bytes,
        "size_mb": usage.total_megabytes,
        "areas": {
            a.name: {"entries": a.entries, "bytes": a.bytes, "size_mb": a.megabytes}
            for a in usage.areas
        },
    }
