"""One licence vocabulary for every falaw ledger (falaw#110).

Licences are named by an SPDX identifier where one exists and by a
``LicenseRef-*`` identifier (SPDX's own convention for bespoke terms) where it
does not. The terms ledger (:mod:`falaw.terms`) and the ComfyUI licence screen
(:mod:`falaw.comfyui.licences`) validate against this one definition, so the
same licence is never spelled two ways.

The SPDX list is deliberately a curated subset (:data:`SPDX_IDS`): the ids the
ledgers actually use. Add one here when a row needs it, rather than pulling in
the full list as a dependency.

>>> is_valid_licence("Apache-2.0")
True
>>> is_valid_licence("MIT OR Apache-2.0")
True
>>> is_valid_licence("flux-1-dev-non-commercial-license")
False
"""

from __future__ import annotations

import re

SPDX_IDS = frozenset(
    {
        "AGPL-3.0-only",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "CC-BY-4.0",
        "CC-BY-NC-4.0",
        "CC-BY-SA-4.0",
        "CC0-1.0",
        "GPL-2.0-only",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "ISC",
        "LGPL-2.1-only",
        "LGPL-3.0-only",
        "MIT",
        "MPL-2.0",
        "Unlicense",
        "WTFPL",
    }
)
"""Standard SPDX ids falaw's ledgers use (https://spdx.org/licenses/)."""

UNKNOWN = "unknown"
"""The licence nobody has read yet; a ledger row may carry it."""

LICENSE_REF = re.compile(r"LicenseRef-[A-Za-z0-9.\-]+")
OPERATORS = frozenset({"AND", "OR"})


def _tokens(expression: str) -> list[str]:
    return expression.replace("(", " ").replace(")", " ").split()


def is_valid_licence(expression: str, *, known: frozenset[str] = SPDX_IDS) -> bool:
    """Whether *expression* is ``unknown``, or ids from *known* / ``LicenseRef-*``
    joined by ``AND`` / ``OR``."""
    if expression == UNKNOWN:
        return True
    tokens = _tokens(expression)
    ids, ops = tokens[::2], tokens[1::2]
    return (
        bool(tokens)
        and len(tokens) % 2 == 1
        and all(op in OPERATORS for op in ops)
        and all(i in known or LICENSE_REF.fullmatch(i) for i in ids)
    )


def validate_licence(expression: str, *, known: frozenset[str] = SPDX_IDS) -> str:
    """*expression* itself, or ``ValueError`` saying how to spell it."""
    if not is_valid_licence(expression, known=known):
        raise ValueError(
            f"licence {expression!r} is not an SPDX id from falaw.licences.SPDX_IDS "
            "nor a LicenseRef-* name (use e.g. 'LicenseRef-vendor-terms' for "
            "bespoke terms), nor 'unknown'"
        )
    return expression


__all__ = ["SPDX_IDS", "UNKNOWN", "is_valid_licence", "validate_licence"]
