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
import re
import time
import uuid
from collections.abc import Callable, Iterator, MutableMapping, Sequence
from contextlib import contextmanager
from typing import Any, Literal, Optional

from .cache import _cache_dir
from .core import fal_client_for

__all__ = [
    "FILE_PREFIX",
    "UPLOAD_INDEX_DIRNAME",
    "current_uploader",
    "derive_namespace",
    "file_marker",
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


_DEFAULT_UPLOADER: Optional[tuple[Callable[[str], str], str]] = None
"""Process-wide override of the transfer, with its index namespace (a plain
global, like the URL fetcher in :mod:`falaw.content`: it must be visible from
worker threads)."""


def current_uploader() -> Optional[Callable[[str], str]]:
    """The uploader installed by :func:`using_uploader`, or ``None`` for fal's."""
    return None if _DEFAULT_UPLOADER is None else _DEFAULT_UPLOADER[0]


def derive_namespace(uploader: Callable[[str], str]) -> str:
    """The index namespace of a custom uploader: its ``namespace`` attribute if
    it has one, else a short hash of its qualified name, so two different
    uploaders never share remembered URLs by accident."""
    named = getattr(uploader, "namespace", None)
    if named:
        return str(named)
    qualname = getattr(uploader, "__qualname__", type(uploader).__qualname__)
    ident = f"{getattr(uploader, '__module__', '')}.{qualname}"
    return "custom-" + hashlib.sha1(ident.encode()).hexdigest()[:8]


@contextmanager
def using_uploader(
    uploader: Callable[[str], str], *, namespace: Optional[str] = None
) -> Iterator[Callable[[str], str]]:
    """Make ``uploader`` the transfer for every :func:`upload` (and every local
    file in an executed Plan) for the duration: an S3 uploader, or a fake in a
    test suite. An explicit ``uploader=`` argument still wins. ``namespace``
    keys its URLs in the index (default :func:`derive_namespace`). Nests and
    restores."""
    global _DEFAULT_UPLOADER
    previous = _DEFAULT_UPLOADER
    _DEFAULT_UPLOADER = (uploader, namespace or derive_namespace(uploader))
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
        expires_at = entry.get("expires_at")
        alive = expires_at is None or now < float(expires_at)
    except Exception:  # noqa: BLE001
        return None
    return url if isinstance(url, str) and 0 <= age < ttl_s and alive else None


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
    uploader the object is uploaded with a lifecycle of ``ttl_s`` and the entry
    records when it dies, so a remembered URL is never trusted past that.
    ``namespace`` keeps URLs from different backends apart in a shared index
    (default: ``"fal"``, or :func:`derive_namespace` for another uploader).
    ``api_key`` is used by the default uploader only (see
    :func:`falaw.core.fal_client_for`).
    """
    if ttl_s < 0:
        raise ValueError(f"ttl_s must be >= 0, got {ttl_s}")
    path = os.fspath(path)
    installed = _DEFAULT_UPLOADER
    lifetime_s: Optional[int] = None
    if uploader is None and installed is not None:
        uploader, namespace = installed[0], namespace or installed[1]
    if uploader is None:
        lifetime_s = max(1, int(ttl_s))
        uploader = functools.partial(
            default_uploader, api_key=api_key, expires_in_s=lifetime_s
        )
        namespace = namespace or "fal"
    namespace = namespace or derive_namespace(uploader)
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
        record = {"url": url, "uploaded_at": now}
        if lifetime_s is not None:
            record["expires_at"] = now + lifetime_s
        index[key] = record
    return url


# --- local files inside a Plan --------------------------------------------------

FILE_PREFIX = "<file "
"""Marks a local file where a Plan argument would hold a URL:
``"<file sha256:<hex> /abs/x.png>"``. The digest makes the Plan's identity (and
the cache key) follow the file's bytes; the path says where to read them."""

_MARKER = re.compile(r"<file sha256:([0-9a-f]{64}) (.+)>", re.DOTALL)

Pointer = tuple  # of dict keys / list indices leading to one argument


def file_marker(path: str | os.PathLike) -> str:
    """The marker for ``path``, digesting its bytes now (``FileNotFoundError``
    if it is not there — refused while planning is still free)."""
    path = os.path.abspath(os.fspath(path))
    return f"{FILE_PREFIX}sha256:{file_digest(path)} {path}>"


def localize_paths(arguments: Any) -> tuple[Any, tuple[Pointer, ...]]:
    """``(arguments', pointers)``: every ``os.PathLike`` replaced by its marker,
    and where each one sits. The Plan stays pure data, and **only the declared
    pointers are ever resolved** — a prompt that happens to look like a marker
    is just text and can never make falaw read a file."""
    pointers: list[Pointer] = []

    def walk(value: Any, at: Pointer) -> Any:
        if isinstance(value, os.PathLike):
            pointers.append(at)
            return file_marker(value)
        if isinstance(value, dict):
            return {k: walk(v, (*at, k)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            items = [walk(v, (*at, i)) for i, v in enumerate(value)]
            return items if isinstance(value, list) else tuple(items)
        return value

    return walk(arguments, ()), tuple(pointers)


def _replace_at(node: Any, pointer: Pointer, fn: Callable[[Any], Any]) -> Any:
    """``node`` with ``fn`` applied at ``pointer`` (containers copied on the way)."""
    if not pointer:
        return fn(node)
    head, rest = pointer[0], pointer[1:]
    if isinstance(node, dict):
        return {**node, head: _replace_at(node[head], rest, fn)}
    items = list(node)
    items[head] = _replace_at(items[head], rest, fn)
    return items if isinstance(node, list) else tuple(items)


def resolve_local_files(
    arguments: Any,
    pointers: Sequence[Pointer],
    *,
    mode: Literal["wire", "key"],
    uploader: Optional[Callable[[str], str]] = None,
    index: Optional[MutableMapping[str, Any]] = None,
) -> Any:
    """Resolve the declared file markers: ``"wire"`` uploads (:func:`upload`) and
    yields the URL fal fetches, refusing a file that changed since planning;
    ``"key"`` yields ``sha256:<digest>``, the identity the cache keys on (no
    file is read)."""
    from .plan import CONTENT_REF_PREFIX

    def leaf(value: Any) -> str:
        match = _MARKER.fullmatch(value) if isinstance(value, str) else None
        if match is None:
            raise ValueError(f"declared local file is not a file marker: {value!r}")
        digest, path = match.groups()
        if mode == "key":
            return f"{CONTENT_REF_PREFIX}{digest}"
        if file_digest(path) != digest:
            raise ValueError(
                f"{path} changed since the Plan was made (its sha256 no longer "
                "matches); re-plan so the cache key names the bytes that are sent."
            )
        return upload(path, uploader=uploader, index=index)

    for pointer in pointers:
        arguments = _replace_at(arguments, tuple(pointer), leaf)
    return arguments
