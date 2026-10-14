"""Refresh fal.ai docs locally with conditional GETs.

Three layers, cheapest first:

* ``is_stale(source)`` --- HEAD with ``If-None-Match``; near-zero cost.
* ``fetch_if_changed(source)`` --- conditional GET; saves and snapshots if changed.
* ``refresh_llms()`` / ``refresh_full_docs()`` --- coordinate fetches across
  the doc set, save previous-version snapshots for diffing, journal results.

State (per-source ETag and Last-Modified) is kept under
``$FALAW_DATA_DIR/refresh/state.json`` (default ``~/.config/falaw/refresh/``);
previous-version snapshots live alongside as ``<source>.prev`` so a successful
refresh can be diffed against the prior content.

For scheduled / remote runs, set ``FALAW_DATA_DIR`` to a path *inside* the
repo (e.g. ``misc/falaw_state``) so journal entries and refresh state are
committed back to the repo on each run.
"""

from __future__ import annotations

import concurrent.futures
import difflib
import json
import os
import re
import time
import urllib.error
import urllib.request
from contextvars import copy_context
from dataclasses import dataclass
from typing import Optional

from .journal import _default_journal
from .registry import register_tool


# ---- locations -----------------------------------------------------------


def _state_dir() -> str:
    base = os.environ.get("FALAW_DATA_DIR") or os.path.expanduser("~/.config/falaw")
    d = os.path.join(base, "refresh")
    os.makedirs(d, exist_ok=True)
    return d


def _state_path() -> str:
    return os.path.join(_state_dir(), "state.json")


def _snapshot_path(name: str) -> str:
    return os.path.join(_state_dir(), f"{name}.prev")


def _load_state() -> dict:
    if not os.path.exists(_state_path()):
        return {}
    with open(_state_path()) as f:
        return json.load(f)


def _save_state(state: dict) -> None:
    with open(_state_path(), "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def _docs_dir() -> str:
    """Default docs location: ``<repo>/misc/docs`` when used from a checkout."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "misc", "docs"))


# ---- DocSource -----------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class DocSource:
    """A single document mirrored locally."""

    name: str
    url: str
    local_path: str


def default_sources(*, docs_dir: Optional[str] = None) -> list[DocSource]:
    docs_dir = docs_dir or _docs_dir()
    return [
        DocSource(
            name="llms",
            url="https://fal.ai/llms.txt",
            local_path=os.path.join(docs_dir, "llms.txt"),
        ),
        DocSource(
            name="llms-full",
            url="https://fal.ai/llms-full.txt",
            local_path=os.path.join(docs_dir, "llms-full.txt"),
        ),
    ]


# ---- HTTP helpers --------------------------------------------------------


def _request(
    url: str,
    *,
    method: str = "GET",
    extra_headers: Optional[dict] = None,
    timeout: float = 30.0,
) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(
        url,
        method=method,
        headers={"User-Agent": "falaw-refresh/0.1", **(extra_headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read() if method == "GET" else b""
            return resp.status, dict(resp.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), b""


def _conditional_headers(source: DocSource, state: dict) -> dict:
    s = state.get(source.name) or {}
    headers: dict = {}
    if s.get("etag"):
        headers["If-None-Match"] = s["etag"]
    if s.get("last_modified"):
        headers["If-Modified-Since"] = s["last_modified"]
    return headers


def _hdr(headers: dict, name: str) -> str:
    return (headers.get(name) or headers.get(name.title()) or "").strip()


# ---- public API ----------------------------------------------------------


def is_stale(source: DocSource, *, state: Optional[dict] = None) -> bool:
    """Cheap HEAD: True iff the upstream ETag differs from saved state."""
    state = state if state is not None else _load_state()
    status, headers, _ = _request(
        source.url, method="HEAD", extra_headers=_conditional_headers(source, state)
    )
    if status == 304:
        return False
    upstream_etag = _hdr(headers, "etag")
    saved_etag = (state.get(source.name) or {}).get("etag", "")
    return upstream_etag != saved_etag


def fetch_if_changed(
    source: DocSource, *, save_snapshot: bool = True
) -> tuple[bool, str]:
    """Conditional GET. Updates the local file and saved state on a real change.

    Returns ``(changed, body)``: ``changed`` is False on 304 (or any non-200);
    ``body`` is the new text only when changed.
    """
    state = _load_state()
    status, resp_headers, body = _request(
        source.url, method="GET", extra_headers=_conditional_headers(source, state)
    )

    if status == 304:
        return False, ""

    if status != 200:
        _default_journal().append(
            kind="issue",
            text=f"refresh: GET {source.url} returned status={status}",
            tags=("refresh", "http_error"),
            context={"source": source.name},
        )
        return False, ""

    text = body.decode("utf-8", errors="replace")

    if save_snapshot and os.path.exists(source.local_path):
        prev = _snapshot_path(source.name)
        os.makedirs(os.path.dirname(prev), exist_ok=True)
        with open(source.local_path, "rb") as src, open(prev, "wb") as dst:
            dst.write(src.read())

    os.makedirs(os.path.dirname(source.local_path) or ".", exist_ok=True)
    with open(source.local_path, "w") as f:
        f.write(text)

    state[source.name] = {
        "etag": _hdr(resp_headers, "etag"),
        "last_modified": _hdr(resp_headers, "last-modified"),
        "fetched_at": time.time(),
        "size": len(text),
    }
    _save_state(state)
    return True, text


def diff_against_previous(source: DocSource, *, n_context: int = 3) -> str:
    """Unified diff: previous snapshot vs current local file."""
    prev = _snapshot_path(source.name)
    if not (os.path.exists(prev) and os.path.exists(source.local_path)):
        return ""
    with open(prev) as a, open(source.local_path) as b:
        return "".join(
            difflib.unified_diff(
                a.readlines(),
                b.readlines(),
                fromfile=f"{source.name}.prev",
                tofile=source.name,
                n=n_context,
            )
        )


@register_tool(
    name="refresh_llms",
    description=(
        "Refresh `llms.txt` and `llms-full.txt` from fal.ai using conditional "
        "GETs (ETag-based). Cheap: returns immediately if nothing changed. "
        "On change, snapshots the previous version and journals the diff. "
        "Returns a summary dict like {'llms': {'changed': False}, ...}."
    ),
    tags=("refresh", "maintenance"),
    input_schema={
        "type": "object",
        "properties": {
            "docs_dir": {"type": "string"},
            "journal": {"type": "boolean", "default": True},
        },
    },
    output_schema={"type": "object"},
)
def refresh_llms(
    *,
    docs_dir: Optional[str] = None,
    journal: bool = True,
) -> dict:
    """Refresh ``llms.txt`` and ``llms-full.txt``; return a summary dict."""
    summary: dict = {}
    for source in default_sources(docs_dir=docs_dir):
        changed, _ = fetch_if_changed(source)
        summary[source.name] = {"changed": changed}
        if changed and journal:
            diff = diff_against_previous(source)
            preview = "\n".join(diff.splitlines()[:60])
            _default_journal().append(
                kind="note",
                text=f"refresh: {source.name} changed",
                tags=("refresh", source.name),
                context={"diff_preview": preview, "diff_size": len(diff)},
            )
    return summary


# ---- per-page docs crawl -------------------------------------------------


_INDEX_LINK_RE = re.compile(r"\[[^\]]*\]\((https://fal\.ai/[^)\s]+\.md)\)")


def _parse_index(index_path: str) -> list[str]:
    """Pull docs URLs from `fal_ai_docs_index.md`. Deduplicates, preserves order."""
    with open(index_path) as f:
        text = f.read()
    return list(dict.fromkeys(_INDEX_LINK_RE.findall(text)))


@register_tool(
    name="refresh_full_docs",
    description=(
        "Re-crawl every per-page .md endpoint listed in `fal_ai_docs_index.md` "
        "with conditional GETs, then reassemble `fal_ai_docs_full.md`. Heavy. "
        "Gated on `is_stale(llms-full)` by default --- pass `force=True` to "
        "skip the gate. Pages that 304 are skipped; only changed pages "
        "re-download. Logs a single journal entry summarizing the run."
    ),
    tags=("refresh", "maintenance"),
    input_schema={
        "type": "object",
        "properties": {
            "docs_dir": {"type": "string"},
            "max_workers": {"type": "integer", "default": 16},
            "force": {"type": "boolean", "default": False},
            "journal": {"type": "boolean", "default": True},
        },
    },
    output_schema={"type": "object"},
)
def refresh_full_docs(
    *,
    docs_dir: Optional[str] = None,
    max_workers: int = 16,
    force: bool = False,
    journal: bool = True,
) -> dict:
    """Re-crawl per-page docs and rebuild ``fal_ai_docs_full.md``."""
    docs_dir = docs_dir or _docs_dir()
    index_path = os.path.join(docs_dir, "fal_ai_docs_index.md")
    full_md_path = os.path.join(docs_dir, "fal_ai_docs_full.md")

    if not force:
        llms_full = next(
            s for s in default_sources(docs_dir=docs_dir) if s.name == "llms-full"
        )
        if not is_stale(llms_full):
            return {
                "skipped": "llms-full unchanged",
                "hint": "pass force=True to override",
            }

    if not os.path.exists(index_path):
        return {"error": f"missing index file: {index_path}"}

    urls = _parse_index(index_path)
    state = _load_state()
    pages_dir = os.path.join(_state_dir(), "pages")
    os.makedirs(pages_dir, exist_ok=True)

    def _fetch_one(url: str) -> tuple[str, int]:
        slug = url.replace("https://", "").replace("/", "_")
        local = os.path.join(pages_dir, slug)
        s = state.get(slug) or {}
        headers: dict = {}
        if s.get("etag"):
            headers["If-None-Match"] = s["etag"]
        status, resp_headers, body = _request(url, extra_headers=headers)
        if status == 200:
            with open(local, "wb") as f:
                f.write(body)
            state[slug] = {
                "etag": _hdr(resp_headers, "etag"),
                "fetched_at": time.time(),
            }
        return url, status

    changed: list[str] = []
    errors: list[tuple[str, int]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        # Same context-carrying rule as ``execute_plan``: a bare pool drops
        # contextvars (e.g. a bound BYO key). One copy per task, taken here on
        # the calling thread; ``pool.map`` (not ``submit``) keeps its
        # cancel-the-rest-on-first-error behaviour.
        contexts = [copy_context() for _ in urls]
        for url, status in pool.map(
            lambda ctx, u: ctx.run(_fetch_one, u), contexts, urls
        ):
            if status == 200:
                changed.append(url)
            elif status != 304:
                errors.append((url, status))

    _save_state(state)

    parts: list[str] = []
    for url in urls:
        slug = url.replace("https://", "").replace("/", "_")
        local = os.path.join(pages_dir, slug)
        if not os.path.exists(local):
            continue
        with open(local) as f:
            parts.append(f"\n\n# {url}\n\n" + f.read())
    with open(full_md_path, "w") as out:
        out.write("".join(parts))

    summary = {
        "total_urls": len(urls),
        "changed": len(changed),
        "errors": len(errors),
        "full_md": full_md_path,
    }
    if journal:
        _default_journal().append(
            kind="issue" if errors else "note",
            text=(
                f"refresh_full_docs: {len(changed)}/{len(urls)} pages changed, "
                f"{len(errors)} errors"
            ),
            tags=("refresh", "full_docs"),
            context={"errors_sample": errors[:10]},
        )
    return summary


def refresh_state() -> dict:
    """Return the saved per-source refresh state (etags, last fetch times)."""
    return _load_state()
