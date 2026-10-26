"""Result wrapper: parse fal responses into typed assets, lazy download."""

from __future__ import annotations

import mimetypes
import os
import warnings
from dataclasses import dataclass, field
from typing import Any, Optional


def _fetch(url: str) -> bytes:
    """Asset bytes through falaw's one transport (``falaw.content``)."""
    from falaw.content import default_url_fetcher

    return b"".join(default_url_fetcher()(url))


_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF8", ".gif"),
)


def sniff_extension(data: bytes) -> str:
    """Extension implied by the leading bytes ('' if unrecognised)."""
    head = data[:2048]
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if text.startswith((b"<svg", b"<?xml")) and b"<svg" in head.lower():
        return ".svg"
    return ""


def _same_format(suffix: str, sniffed: str) -> bool:
    norm = {".jpeg": ".jpg"}
    suffix = suffix.lower()
    return norm.get(suffix, suffix) == sniffed


@dataclass(frozen=True, slots=True)
class Asset:
    """A single piece of generated media.

    Holds the URL plus minimal typed metadata. `download` materializes it.
    """

    url: str
    kind: str  # "image" | "video" | "audio" | "other"
    content_type: str = ""
    width: int = 0
    height: int = 0
    duration_s: float = 0.0
    metadata: dict = field(default_factory=dict)

    def download(self, *, to: Optional[str] = None, fix_suffix: bool = False) -> str:
        """Download the asset to a file. Returns the local path.

        The bytes are sniffed: some models return a different format than the
        usual one (Recraft's ``vector_illustration/*`` styles return SVG, not
        PNG). If the suffix of ``to`` contradicts the content, a
        ``UserWarning`` is issued; with ``fix_suffix=True`` the suffix is
        corrected instead (so the returned path may differ from ``to``).
        """
        data = _fetch(self.url)
        sniffed = sniff_extension(data)
        if to is None:
            to = os.path.join(
                os.getcwd(),
                f"falaw_asset_{abs(hash(self.url)) % 10**8}"
                f"{sniffed or self._infer_extension()}",
            )
        elif sniffed and not _same_format(os.path.splitext(to)[1], sniffed):
            if fix_suffix:
                to = os.path.splitext(to)[0] + sniffed
            else:
                warnings.warn(
                    f"{to!r}: content is {sniffed!r} but the suffix says "
                    f"{os.path.splitext(to)[1]!r}; some models return a different "
                    "format than usual (e.g. Recraft vector_illustration/* "
                    "styles return SVG). Pass fix_suffix=True to correct it.",
                    UserWarning,
                    stacklevel=2,
                )
        parent = os.path.dirname(os.path.abspath(to))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(to, "wb") as f:
            f.write(data)
        return to

    def _infer_extension(self) -> str:
        if self.content_type:
            ext = mimetypes.guess_extension(self.content_type) or ""
            if ext:
                return ext
        return {"image": ".png", "video": ".mp4", "audio": ".mp3"}.get(
            self.kind, ".bin"
        )


@dataclass(slots=True)
class Result:
    """A fal call result with parsed assets and the original raw response.

    The raw response is kept so callers can inspect provider-specific fields
    (timings, seed, has_nsfw_concepts, ...) that we do not normalize.
    """

    assets: list[Asset] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    application: str = ""
    arguments: dict = field(default_factory=dict)

    @property
    def first(self) -> Optional[Asset]:
        return self.assets[0] if self.assets else None

    def download_all(self, *, to_dir: Optional[str] = None) -> list[str]:
        to_dir = to_dir or os.getcwd()
        os.makedirs(to_dir, exist_ok=True)
        paths: list[str] = []
        stem_base = self.application.replace("/", "_") or "asset"
        for i, a in enumerate(self.assets):
            path = os.path.join(to_dir, f"{stem_base}_{i}{a._infer_extension()}")
            paths.append(a.download(to=path, fix_suffix=True))
        return paths


# response shape -> (key in raw response, asset kind)
_KIND_KEYS = (
    ("images", "image"),
    ("image", "image"),
    ("videos", "video"),
    ("video", "video"),
    ("audios", "audio"),
    ("audio", "audio"),
    ("audio_url", "audio"),
)


def parse_response(
    raw: dict,
    *,
    application: str,
    arguments: dict,
) -> Result:
    """Best-effort parser over the common fal response shapes.

    fal models return a variety of layouts (lists, single objects, bare URLs).
    We normalize each into Asset(url, kind, ...). Unknown shapes pass through
    as `raw` only --- callers can read `result.raw` for anything we miss.
    """
    assets: list[Asset] = []
    if isinstance(raw, dict):
        seen_kinds: set[str] = set()
        for key, kind in _KIND_KEYS:
            val = raw.get(key)
            if val is None or kind in seen_kinds:  # Sonilo: audios + audio
                continue
            seen_kinds.add(kind)
            for item in val if isinstance(val, list) else [val]:
                assets.append(_to_asset(item, kind))
    return Result(
        assets=assets,
        raw=raw if isinstance(raw, dict) else {},
        application=application,
        arguments=dict(arguments),
    )


def _to_asset(item: Any, kind: str) -> Asset:
    if isinstance(item, str):
        return Asset(url=item, kind=kind)
    if isinstance(item, dict):
        return Asset(
            url=item.get("url", ""),
            kind=kind,
            content_type=item.get("content_type", ""),
            width=int(item.get("width") or 0),
            height=int(item.get("height") or 0),
            duration_s=float(item.get("duration") or 0),
            metadata={
                k: v
                for k, v in item.items()
                if k not in {"url", "content_type", "width", "height", "duration"}
            },
        )
    return Asset(url=str(item), kind=kind)
