"""HTTP service bridge (planned): expose falaw tools as a `qh` app.

The plan: feed `falaw.registry.list_tools()` callables to `qh.mk_app` so
each tool becomes an HTTP endpoint. Same SSOT, new surface --- no rewrite
of the operations themselves.
"""

from __future__ import annotations


def build_qh_app(*args, **kwargs):
    """Build an HTTP service from the registered tools (not implemented yet)."""
    raise NotImplementedError(
        "Service bridge not yet implemented. Plan: collect callables from "
        "`falaw.registry.list_tools()` and pass them to `qh.mk_app`. See "
        "`bridges/skill.py` for the same SSOT-to-surface pattern."
    )
