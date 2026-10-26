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

import hashlib
import os
import time
from collections.abc import Callable, MutableMapping
from typing import Any, Optional

from .cache import _cache_dir

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


def default_upload_index() -> MutableMapping[str, Any]:
    """The falaw-cache-rooted JSON-file index (constructed per call, so a test
    that re-points the cache dir gets a fresh one)."""
    from dol import JsonFiles

    root = os.path.join(_cache_dir(), UPLOAD_INDEX_DIRNAME)
    os.makedirs(root, exist_ok=True)
    return JsonFiles(root)


def default_uploader(path: str) -> str:
    """Upload with ``fal_client`` under the credentials falaw resolves."""
    from .core import FAL_PROVIDER, resolve_credential
    from .errors import import_fal_client

    fal_client = import_fal_client()
    key = resolve_credential(FAL_PROVIDER, api_key=None, required=False)
    client_cls = getattr(fal_client, "SyncClient", None)
    upload_file = (
        client_cls(key=key).upload_file
        if key and client_cls
        else fal_client.upload_file
    )
    return upload_file(path)


def upload(
    path: str | os.PathLike,
    *,
    uploader: Optional[Callable[[str], str]] = None,
    index: Optional[MutableMapping[str, Any]] = None,
    ttl_s: float = DEFAULT_UPLOAD_TTL_S,
    clock: Callable[[], float] = time.time,
) -> str:
    """A fal-fetchable URL for the local file at ``path``.

    Cached by content: an unchanged file within ``ttl_s`` of its last upload
    returns the remembered URL without any transfer.
    """
    path = os.fspath(path)
    digest = file_digest(path)
    uploader = uploader or default_uploader
    index = default_upload_index() if index is None else index
    now = clock()
    entry = index.get(digest)
    if entry and now - entry["uploaded_at"] < ttl_s:
        return entry["url"]
    url = uploader(path)
    index[digest] = {"url": url, "uploaded_at": now}
    return url
