"""Licence screen for ComfyUI node packs (checklist row L).

Reads each pack's own ``LICENSE`` / ``LICENCE`` / ``COPYING`` file in the
pinned checkout — never registry metadata, which 85.5% of packs leave empty —
and fails on AGPL-family or *undeterminable*. The screen records a digest of
the screened set (:func:`nodes_digest`) so a manifest can prove the screen was
run on the nodes it actually deploys.

AGPL is recognised from the licence's **title** (its first lines) or an SPDX
tag, not from the word "Affero" anywhere in the text: GPLv3 section 13 names
the AGPL, so a substring scan would reject every GPLv3 pack.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..licences import SPDX_IDS, UNKNOWN, is_valid_licence
from .problems import Problem

LICENCE_FILE_PREFIXES = ("LICENSE", "LICENCE", "COPYING")
"""A pack's licence files: any root-level file whose name starts with one."""

TITLE_LINES = 12
"""How many leading non-blank lines count as a licence's title (room for a
copyright line or three above the licence's name)."""

RESTRICTED_FAMILY = re.compile(
    r"AGPL|AFFERO|\bSSPL\b|SERVER SIDE PUBLIC LICENSE", re.IGNORECASE
)
"""The AGPL family plus SSPL (same network-copyleft reach). Matched against a
file's title lines and SPDX tags, not its whole text; see :func:`_is_restricted`."""

AGPL_TITLE = "GNU AFFERO GENERAL PUBLIC LICENSE"
"""The AGPL's own upper-case title, flagged wherever it sits in a file. GPLv3
section 13 names the licence in mixed case, so this does not flag GPLv3."""

SPDX_TAG = re.compile(
    r"SPDX-License-Identifier:[ \t]*([^\r\n*]+?)[ \t]*(?:\*/|-->)?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
"""A tag's expression, up to the end of its line or a closing comment marker."""

SPDX_TAG_ANYWHERE = re.compile(r"SPDX-License-Identifier:\s*(.+)", re.IGNORECASE)
"""Everything after a tag to the end of its line. The restricted check reads
this, not :data:`SPDX_TAG`: it must see an AGPL tag however the line is decorated."""

EXCEPTION = re.compile(r"\s+WITH\s+\S+", re.IGNORECASE)
"""An SPDX ``WITH <exception>`` suffix: the exception does not change which licence it is."""

KNOWN_LICENCES = {
    "MIT": r"\bMIT License\b|Permission is hereby granted, free of charge",
    "Apache-2.0": r"Apache License,?\s+Version 2",
    "LicenseRef-BSD-family": r"Redistribution and use in source and binary forms",
    "LicenseRef-GPL-family": r"GNU (?:LESSER |LIBRARY )?GENERAL PUBLIC LICENSE",
    "MPL-2.0": r"Mozilla Public License",
    "ISC": r"\bISC License\b|Permission to use, copy, modify, and/or distribute",
    "Unlicense": r"This is free and unencumbered software",
    "CC0-1.0": r"CC0 1\.0|Creative Commons Zero",
    "WTFPL": r"DO WHAT THE FUCK YOU WANT",
}
"""Licences recognised as *determinable* (keyed in the shared
:mod:`falaw.licences` vocabulary; a ``-family`` spans several SPDX ids), looked
for in a file's title lines. Text matching none of these is undeterminable, which fails the screen: terms
we cannot read are not a pass. A heuristic by design; what it cannot place
goes to a human."""


def nodes_digest(nodes: Iterable[tuple[str, str]]) -> str:
    """SHA-256 over the ``(pack name, commit)`` pairs, order-independent."""
    pairs = sorted((str(n), str(c)) for n, c in nodes)
    return hashlib.sha256(json.dumps(pairs).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LicenceScreen:
    """The outcome of :func:`screen_licences`, in manifest shape."""

    checked_at: str
    nodes_digest: str
    agpl_packs: tuple[str, ...] = field(default=())
    undeterminable: tuple[str, ...] = field(default=())

    @property
    def passed(self) -> bool:
        return not (self.agpl_packs or self.undeterminable)

    def to_dict(self) -> dict:
        """The ``licence_screen`` block of the deployment manifest."""
        return {
            "checked_at": self.checked_at,
            "nodes_digest": self.nodes_digest,
            "agpl_packs": list(self.agpl_packs),
            "undeterminable": list(self.undeterminable),
        }

    def problems(self) -> list[Problem]:
        return [
            *(Problem("L", f"{p!r} is AGPL-family") for p in self.agpl_packs),
            *(
                Problem("L", f"{p!r}: licence undeterminable")
                for p in self.undeterminable
            ),
        ]


def _licence_files(pack: Path) -> list[Path]:
    if pack.is_file():  # a single-file node has no licence file of its own
        return []
    return sorted(
        f
        for f in pack.iterdir()
        if f.is_file() and f.name.upper().startswith(LICENCE_FILE_PREFIXES)
    )


def _title(text: str) -> str:
    return " ".join([ln for ln in text.splitlines() if ln.strip()][:TITLE_LINES])


def _is_restricted(text: str) -> bool:
    tags = " ".join(SPDX_TAG_ANYWHERE.findall(text))
    return bool(
        AGPL_TITLE in text
        or RESTRICTED_FAMILY.search(_title(text))
        or RESTRICTED_FAMILY.search(tags)
    )


def _is_known_tag(tag: str) -> bool:
    """A tag naming standard SPDX ids only: ``unknown`` and ``LicenseRef-*`` are
    the vocabulary's words for terms nobody has read, so they cannot make a
    licence determinable here."""
    if tag.lower() == UNKNOWN or "licenseref-" in tag.lower():
        return False
    canonical = {i.lower(): i for i in SPDX_IDS}
    words = [
        canonical.get(w.lower(), w)
        for w in tag.replace("(", " ( ").replace(")", " ) ").split()
    ]
    return is_valid_licence(" ".join(words).replace("( ", "(").replace(" )", ")"))


def _is_determinable(text: str) -> bool:
    """Whether the file's licence can be read: SPDX tags, when it has any, must
    all be in the shared vocabulary (:func:`falaw.licences.is_valid_licence`);
    one that is not makes it undeterminable, whatever the text says. Without a
    tag, the title must match a :data:`KNOWN_LICENCES` pattern."""
    tags = [EXCEPTION.sub("", t).strip() for t in SPDX_TAG.findall(text)]
    if tags:
        return all(_is_known_tag(t) for t in tags)
    title = _title(text)
    return any(re.search(p, title, re.IGNORECASE) for p in KNOWN_LICENCES.values())


def _classify(pack: Path) -> str:
    """``"agpl"``, ``"undeterminable"`` or ``"ok"`` — each file judged on its
    own, so one permissive file cannot vouch for a restrictive sibling."""
    texts = [f.read_text(errors="replace") for f in _licence_files(pack)]
    if any(_is_restricted(t) for t in texts):
        return "agpl"
    if not texts or not all(_is_determinable(t) for t in texts):
        return "undeterminable"
    return "ok"


def git_head(pack: Path) -> str:
    """The commit checked out in ``pack`` (``git rev-parse HEAD``); ``""`` when
    ``pack`` is not a git checkout (it cannot be pinned, so it cannot pass)."""
    try:
        return subprocess.run(
            ["git", "-C", str(pack), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError):
        return ""


def screen_licences(
    nodes_dir: str | Path,
    *,
    only: Optional[Collection[str]] = None,
    commit_of: Callable[[Path], str] = git_head,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> LicenceScreen:
    """Screen every node pack (a directory, or a single ``.py`` file) under ``nodes_dir``.

    ``only`` restricts the screen to the manifest's declared packs (a stock
    ComfyUI checkout also carries unrelated example nodes under
    ``custom_nodes/``). ``commit_of`` reads each pack's pinned commit (default: its git ``HEAD``)
    so the returned ``nodes_digest`` matches
    :func:`nodes_digest` of the manifest's ``custom_nodes``.
    """
    agpl, unknown, identity = [], [], []
    for pack in sorted(
        p
        for p in Path(nodes_dir).iterdir()
        if not p.name.startswith((".", "__"))
        and (p.is_dir() or p.suffix == ".py")
        and (only is None or p.name in only)
    ):
        commit = commit_of(pack)
        identity.append((pack.name, commit))
        verdict = _classify(pack)
        if verdict == "agpl":
            agpl.append(pack.name)
        elif verdict == "undeterminable" or not commit:
            unknown.append(pack.name)
    return LicenceScreen(
        checked_at=clock().isoformat(timespec="seconds"),
        nodes_digest=nodes_digest(identity),
        agpl_packs=tuple(agpl),
        undeterminable=tuple(unknown),
    )
