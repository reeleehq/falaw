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

Whether a *Plan* should accept a local path directly and upload at execute time
(keeping the Plan pure data, with the digest in the cache key) is left open;
:func:`upload` is the building block either way.

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
from collections.abc import Callable, MutableMapping
from typing import Any, Optional

from .cache import _cache_dir
from .core import fal_client_for

__all__ = [
    "UPLOAD_INDEX_DIRNAME",
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


def default_uploader(path: str, *, api_key: Optional[str] = None) -> str:
    """Upload with ``fal_client`` under the credentials falaw resolves."""
    return fal_client_for(api_key).upload_file(path)


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
    api_key: Optional[str] = None,
    clock: Callable[[], float] = time.time,
) -> str:
    """A fal-fetchable URL for the local file at ``path``.

    Cached by content: an unchanged file within ``ttl_s`` of its last upload
    returns the remembered URL without any transfer. ``api_key`` is used by the
    default uploader only (see :func:`falaw.core.fal_client_for`).
    """
    if ttl_s < 0:
        raise ValueError(f"ttl_s must be >= 0, got {ttl_s}")
    path = os.fspath(path)
    digest = file_digest(path)
    if uploader is None:
        uploader = functools.partial(default_uploader, api_key=api_key)
    index = default_upload_index() if index is None else index
    now = clock()
    try:
        entry = index.get(digest)
    except Exception:  # noqa: BLE001 — an unreadable entry is a miss
        entry = None
    url = _fresh_url(entry, now, ttl_s) if entry else None
    if url is None:
        url = uploader(path)
        index[digest] = {"url": url, "uploaded_at": now}
    return url
