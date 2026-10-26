"""``upload`` — a local file in, a fal-fetchable URL out (falaw#87).

Image-to-video and image-edit calls take an image *URL* that fal can fetch;
a production that starts from local files (a keyframe still, the last frame of
the previous clip) needs a way to get one. :func:`upload` is that, fitted to
falaw's content-address model rather than handing out an arbitrary URL:

* the file is identified by the SHA-256 of its **bytes**, so an unchanged file
  is not uploaded twice, and two paths with the same bytes share one upload;
* fal URLs are not durable (see :mod:`falaw.content`), so each index entry
  carries its upload time and is **re-uploaded once it is older than**
  ``ttl_s`` instead of being trusted forever.

Two seams, both keyword arguments: ``uploader`` (the transfer — default
``fal_client.upload_file`` under the key bound via
:func:`falaw.using_fal_credentials`) and ``index`` (a ``MutableMapping``
digest -> ``{"url", "uploaded_at"}`` — default a directory of JSON files under
the falaw cache dir, so it moves with ``$FALAW_CACHE_DIR``).

A *Plan* may also name a local file directly (falaw#92): ``make_call_plan``
turns any ``os.PathLike`` argument into a ``"<file /abs/path>"`` marker, so the
Plan stays pure data. At execute time the marker becomes the uploaded URL on the
wire (uploaded only on a cache miss) and ``sha256:<digest of the bytes>`` in the
cache key, so an unchanged file hits the cache and an edited one cannot.
:func:`using_uploader` replaces the transfer for the whole process.

>>> upload("keyframe.png", uploader=lambda p: "https://v3b.fal.media/x.png", index={})  # doctest: +SKIP
'https://v3b.fal.media/x.png'
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable, Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any, Literal, Optional

from .cache import _cache_dir
from .core import fal_client_for

__all__ = [
    "FILE_PREFIX",
    "UPLOAD_INDEX_DIRNAME",
    "current_uploader",
    "file_marker",
    "has_local_files",
    "localize_paths",
    "resolve_local_files",
    "using_uploader",
    "DEFAULT_UPLOAD_TTL_S",
    "default_upload_index",
    "default_uploader",
    "file_digest",
    "upload",
]

UPLOAD_INDEX_DIRNAME = "uploads"
"""Directory under the falaw cache root holding the digest -> URL index."""

DEFAULT_UPLOAD_TTL_S = 24 * 3600
"""How long an uploaded URL is trusted. fal documents that expired files are
deleted but no fixed lifetime we can rely on, so this is a conservative bound;
a stale entry costs one re-upload, a trusted dead URL costs a failed paid call."""

_HASH_CHUNK_BYTES = 1 << 20


def file_digest(path: str | os.PathLike) -> str:
    """SHA-256 hex digest of the file's bytes (streamed)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_HASH_CHUNK_BYTES):
            h.update(chunk)
    return h.hexdigest()


class _AtomicJsonFiles:
    """A directory of ``<digest>`` JSON files, written via temp file + rename.

    ``dol.JsonFiles`` truncates in place, so a crash (or a concurrent reader)
    leaves a half-written file; this keeps the same mapping surface with the
    write made atomic, as :mod:`falaw.content`'s ``url_index`` does.
    """

    def __new__(cls, rootdir: str):
        from dol import JsonFiles

        class _Index(JsonFiles):
            def __setitem__(self, key, value):
                tmp = os.path.join(rootdir, f"{key}.{uuid.uuid4().hex[:8]}.part")
                with open(tmp, "w") as f:
                    json.dump(value, f)
                os.replace(tmp, os.path.join(rootdir, key))

        return _Index(rootdir)


def default_upload_index() -> MutableMapping[str, Any]:
    """The falaw-cache-rooted JSON-file index (constructed per call, so a test
    that re-points the cache dir gets a fresh one)."""
    root = os.path.join(_cache_dir(), UPLOAD_INDEX_DIRNAME)
    os.makedirs(root, exist_ok=True)
    return _AtomicJsonFiles(root)


def default_uploader(
    path: str, *, api_key: Optional[str] = None, expires_in_s: Optional[int] = None
) -> str:
    """Upload with ``fal_client`` under the credentials falaw resolves.

    ``expires_in_s`` asks fal to keep the object at least that long (its
    ``lifecycle`` setting), which is what turns :func:`upload`'s ``ttl_s`` from
    a guess into a guarantee.
    """
    client = fal_client_for(api_key)
    if expires_in_s is None:
        return client.upload_file(path)
    from .errors import import_fal_client

    lifecycle = import_fal_client().StorageSettings(expires_in=int(expires_in_s))
    return client.upload_file(path, lifecycle=lifecycle)


_DEFAULT_UPLOADER: Optional[Callable[[str], str]] = None
"""Process-wide override of the transfer (a plain global, like the URL fetcher
in :mod:`falaw.content`: it must be visible from worker threads)."""


def current_uploader() -> Optional[Callable[[str], str]]:
    """The uploader installed by :func:`using_uploader`, or ``None`` for fal's."""
    return _DEFAULT_UPLOADER


@contextmanager
def using_uploader(uploader: Callable[[str], str]) -> Iterator[Callable[[str], str]]:
    """Make ``uploader`` the transfer for every :func:`upload` (and every local
    file in an executed Plan) for the duration: an S3 uploader, or a fake in a
    test suite. An explicit ``uploader=`` argument still wins. Nests and restores."""
    global _DEFAULT_UPLOADER
    previous, _DEFAULT_UPLOADER = _DEFAULT_UPLOADER, uploader
    try:
        yield uploader
    finally:
        _DEFAULT_UPLOADER = previous


def _fresh_url(entry: Any, now: float, ttl_s: float) -> Optional[str]:
    """The entry's URL if it is well-formed and within ``ttl_s``, else ``None``.

    A corrupt or foreign entry is a miss, never a failure (it is only a hint);
    an ``uploaded_at`` in the future (clock skew) is not trusted.
    """
    try:
        age = now - float(entry["uploaded_at"])
        url = entry["url"]
    except Exception:  # noqa: BLE001
        return None
    return url if isinstance(url, str) and 0 <= age < ttl_s else None


def upload(
    path: str | os.PathLike,
    *,
    uploader: Optional[Callable[[str], str]] = None,
    index: Optional[MutableMapping[str, Any]] = None,
    ttl_s: float = DEFAULT_UPLOAD_TTL_S,
    namespace: Optional[str] = None,
    api_key: Optional[str] = None,
    clock: Callable[[], float] = time.time,
) -> str:
    """A fal-fetchable URL for the local file at ``path``.

    Cached by content: an unchanged file within ``ttl_s`` of its last upload
    returns the remembered URL without any transfer. With the default fal
    uploader the object is also uploaded with a lifecycle of ``ttl_s``, so a
    remembered URL is still alive when it is trusted. ``namespace`` (default
    ``"fal"`` for fal's uploader, ``"custom"`` for another) keeps URLs from
    different backends apart in a shared index. ``api_key`` is used by the
    default uploader only (see :func:`falaw.core.fal_client_for`).
    """
    if ttl_s < 0:
        raise ValueError(f"ttl_s must be >= 0, got {ttl_s}")
    path = os.fspath(path)
    uploader = uploader or current_uploader()
    if uploader is None:
        uploader = functools.partial(
            default_uploader, api_key=api_key, expires_in_s=max(1, int(ttl_s))
        )
        namespace = namespace or "fal"
    namespace = namespace or "custom"
    key = f"{namespace}-{file_digest(path)}"
    index = default_upload_index() if index is None else index
    now = clock()
    try:
        entry = index.get(key)
    except Exception:  # noqa: BLE001 — an unreadable entry is a miss
        entry = None
    url = _fresh_url(entry, now, ttl_s) if entry else None
    if url is None:
        url = uploader(path)
        index[key] = {"url": url, "uploaded_at": now}
    return url


# --- local files inside a Plan --------------------------------------------------

FILE_PREFIX = "<file "
"""Marks a local file where a Plan argument would hold a URL: ``"<file /abs/x.png>"``."""


def file_marker(path: str | os.PathLike) -> str:
    return f"{FILE_PREFIX}{os.path.abspath(os.fspath(path))}>"


def _marked_path(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.startswith(FILE_PREFIX) and value.endswith(">"):
        return value[len(FILE_PREFIX) : -1]
    return None


def has_local_files(value: Any) -> bool:
    """Whether ``value`` (an arguments tree) holds a ``"<file ...>"`` marker."""
    if _marked_path(value) is not None:
        return True
    if isinstance(value, dict):
        return any(has_local_files(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(has_local_files(v) for v in value)
    return False


def _map_tree(value: Any, fn: Callable[[Any], Any]) -> Any:
    """``fn`` applied to every leaf of a dict/list/tuple tree (structure kept)."""
    if isinstance(value, dict):
        return {k: _map_tree(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_map_tree(v, fn) for v in value]
    if isinstance(value, tuple):
        return tuple(_map_tree(v, fn) for v in value)
    return fn(value)


def localize_paths(arguments: Any) -> Any:
    """Replace every ``os.PathLike`` in an arguments tree with its file marker,
    so a Plan built from local files is still pure, JSON-native data."""
    return _map_tree(
        arguments, lambda v: file_marker(v) if isinstance(v, os.PathLike) else v
    )


def resolve_local_files(
    arguments: Any,
    *,
    mode: Literal["wire", "key"],
    uploader: Optional[Callable[[str], str]] = None,
    index: Optional[MutableMapping[str, Any]] = None,
) -> Any:
    """Resolve file markers: ``"wire"`` uploads (:func:`upload`) and yields the
    URL fal fetches; ``"key"`` yields ``sha256:<digest>`` of the file's bytes,
    the identity the cache keys on."""
    from .plan import CONTENT_REF_PREFIX

    def leaf(value: Any) -> Any:
        path = _marked_path(value)
        if path is None:
            return value
        if mode == "key":
            return f"{CONTENT_REF_PREFIX}{file_digest(path)}"
        return upload(path, uploader=uploader, index=index)

    return _map_tree(arguments, leaf)
