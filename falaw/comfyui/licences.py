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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .problems import Problem

LICENCE_FILE_PREFIXES = ("LICENSE", "LICENCE", "COPYING")
"""A pack's licence files: any root-level file whose name starts with one."""

TITLE_LINES = 8
"""How many leading non-blank lines count as a licence's title."""

AGPL_FAMILY = re.compile(r"\bAGPL\b|AFFERO", re.IGNORECASE)
"""Matched against the title lines and SPDX tags only (see module docstring)."""

SPDX_TAG = re.compile(r"SPDX-License-Identifier:\s*(.+)", re.IGNORECASE)

KNOWN_LICENCES = {
    "MIT": r"\bMIT License\b|Permission is hereby granted, free of charge",
    "Apache-2.0": r"Apache License,?\s+Version 2",
    "BSD": r"Redistribution and use in source and binary forms",
    "GPL": r"GNU (?:LESSER |LIBRARY )?GENERAL PUBLIC LICENSE",
    "MPL-2.0": r"Mozilla Public License",
    "ISC": r"\bISC License\b|Permission to use, copy, modify, and/or distribute",
    "Unlicense": r"This is free and unencumbered software",
    "CC0": r"CC0 1\.0|Creative Commons Zero",
    "WTFPL": r"DO WHAT THE FUCK YOU WANT",
}
"""Licences recognised as *determinable*. Text matching none of these is
undeterminable, which fails the screen: unreadable terms are not a pass."""


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


def _licence_text(pack: Path) -> str:
    files = sorted(
        f
        for f in pack.iterdir()
        if f.is_file() and f.name.upper().startswith(LICENCE_FILE_PREFIXES)
    )
    return "\n".join(f.read_text(errors="replace") for f in files)


def _is_agpl(text: str) -> bool:
    title = " ".join([ln for ln in text.splitlines() if ln.strip()][:TITLE_LINES])
    tags = " ".join(SPDX_TAG.findall(text))
    return bool(AGPL_FAMILY.search(title) or AGPL_FAMILY.search(tags))


def _is_determinable(text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in KNOWN_LICENCES.values())


def git_head(pack: Path) -> str:
    """The commit checked out in ``pack`` (``git rev-parse HEAD``)."""
    return subprocess.run(
        ["git", "-C", str(pack), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def screen_licences(
    nodes_dir: str | Path,
    *,
    commit_of: Callable[[Path], str] = git_head,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> LicenceScreen:
    """Screen every pack directory under ``nodes_dir``.

    ``commit_of`` reads each pack's pinned commit (default: its git ``HEAD``)
    so the returned ``nodes_digest`` matches
    :func:`nodes_digest` of the manifest's ``custom_nodes``.
    """
    agpl, unknown, identity = [], [], []
    for pack in sorted(
        p
        for p in Path(nodes_dir).iterdir()
        if p.is_dir() and not p.name.startswith((".", "__"))
    ):
        identity.append((pack.name, commit_of(pack)))
        text = _licence_text(pack)
        if _is_agpl(text):
            agpl.append(pack.name)
        elif not _is_determinable(text):
            unknown.append(pack.name)
    return LicenceScreen(
        checked_at=clock().isoformat(timespec="seconds"),
        nodes_digest=nodes_digest(identity),
        agpl_packs=tuple(agpl),
        undeterminable=tuple(unknown),
    )
